"""
Windows打印机实现
包含所有Windows平台的打印机操作
"""

import logging
import platform
import os
import json
import shutil
from typing import List, Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)

# Windows特定导入
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
        import win32con
        import pywintypes
        import pythoncom
        # EnumJobs may deserialize PyTime fields through this pywin32 helper.
        import win32timezone  # noqa: F401
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
    
    try:
        import wmi
        WMI_AVAILABLE = True
    except ImportError:
        WMI_AVAILABLE = False
        logger.warning("WMI module unavailable; falling back to polling for print jobs")
else:
    WIN32_AVAILABLE = False
    WMI_AVAILABLE = False


class WindowsEnterprisePrinter:
    """Windows企业级打印机操作类"""
    
    def __init__(self):
        self.available = WIN32_AVAILABLE
        self._wmi_query_state: Dict[str, str] = {}
        # WMI 批量查询缓存：避免逐打印机重复启动 PowerShell
        self._wmi_batch_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._wmi_batch_cache_time: float = 0.0
        self._wmi_batch_cache_ttl: float = 30.0  # 30 秒缓存
        if not self.available:
            logger.warning("Windows print API unavailable; install pywin32")
    
    def discover_local_printers(self) -> List[Dict]:
        """发现本地已安装的打印机"""
        # 直接调用discover_printers方法，避免重复代码
        return self.discover_printers()
    
    def _print_via_socket(self, ip: str, port: int, file_path: str, job_name: str) -> Dict[str, Any]:
        """通过Socket直接发送到HP Smart Printing打印机
        
        使用HP JetDirect协议（RAW 9100）直接发送打印数据
        
        Args:
            ip: 打印机IP地址
            port: 打印机端口（通常是9100）
            file_path: 文件路径
            job_name: 任务名称
        """
        import socket
        
        try:
            print(f" [INFO] 准备通过Socket发送打印数据: {ip}:{port}")
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}"}
            
            # 读取文件内容
            with open(file_path, 'rb') as f:
                data = f.read()
            
            file_size = len(data)
            
            # 创建Socket连接
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)  # 30秒超时
            
            try:
                sock.connect((ip, port))
                print(f" [INFO] 成功连接到打印机")
                
                # 发送打印数据
                total_sent = 0
                while total_sent < file_size:
                    sent = sock.send(data[total_sent:])
                    if sent == 0:
                        raise RuntimeError("Socket连接断开")
                    total_sent += sent
                    # 发送过程不逐段打印，避免日志过多
                
                print(f" [INFO] 打印数据发送完成: {total_sent} bytes")
                
                return {
                    "success": True,
                    "message": f"HP Smart Printing打印任务已发送 ({file_size} bytes)",
                    "job_id": None,  # Socket打印无法获取job_id
                    "method": "hp_jetdirect",
                    "bytes_sent": total_sent
                }
                
            finally:
                sock.close()
                
        except socket.timeout:
            error_msg = f"连接超时: {ip}:{port}"
            print(f" [ERROR] {error_msg}")
            return {"success": False, "message": error_msg}
        except socket.error as e:
            error_msg = f"Socket错误: {e}"
            print(f" [ERROR] {error_msg}")
            return {"success": False, "message": error_msg}
        except Exception as e:
            error_msg = f"HP Smart Printing打印失败: {e}"
            print(f" [ERROR] {error_msg}")
            import traceback
            traceback.print_exc()
            return {"success": False, "message": error_msg}
    
    def _run_command_with_debug(self, command):
        """执行命令并返回结果"""
        import subprocess
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',  # 忽略无法解码的字符
                timeout=30
            )
            return result
        except Exception as e:
            print(f"执行命令失败: {e}")
            return None

    def _load_settings(self) -> Dict[str, Any]:
        candidates = [
            os.path.join(os.getcwd(), "config.json"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))
        ]
        for config_path in candidates:
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    config = json.load(f)
                return config.get("settings", {})
            except Exception:
                return {}
        return {}

    def _get_setting(self, key: str, default=None):
        settings = self._load_settings()
        return settings.get(key, default)

    def _resolve_path(self, path_value: str):
        if not path_value:
            return None
        if os.path.isabs(path_value):
            abs_path = path_value
        else:
            abs_path = os.path.abspath(path_value)
        return abs_path if os.path.exists(abs_path) else None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _normalize_scale_mode(self, value: Any, default: str = "fit") -> str:
        mode = str(value or "").strip().lower()
        if mode in {"fit", "actual", "fill"}:
            return mode
        return default

    def _detect_pdf_page_size(self, file_path: str) -> Optional[str]:
        """检测 PDF 第一页的纸张尺寸，返回标准尺寸名称"""
        try:
            import fitz
            doc = fitz.open(file_path)
            if doc.page_count == 0:
                doc.close()
                return None
            
            # 获取第一页的媒体框尺寸（点是 PDF 的单位，1 点=1/72 英寸）
            page = doc.load_page(0)
            media_box = page.mediabox
            width_pt = media_box.width
            height_pt = media_box.height
            doc.close()
            
            # 转换为英寸
            width_inch = width_pt / 72.0
            height_inch = height_pt / 72.0
            
            # 映射到标准尺寸
            return self._identify_paper_size(width_inch, height_inch)
        except Exception as e:
            print(f" [WARN] 检测 PDF 页面尺寸失败：{e}")
            return None

    def _detect_pdf_orientation(self, file_path: str) -> Optional[str]:
        """检测 PDF 首页面方向，返回 portrait/landscape"""
        try:
            import fitz
            doc = fitz.open(file_path)
            if doc.page_count == 0:
                doc.close()
                return None
            page = doc.load_page(0)
            rect = page.rect
            doc.close()
            return "landscape" if rect.width > rect.height else "portrait"
        except Exception as e:
            print(f" [WARN] 检测 PDF 页面方向失败：{e}")
            return None

    def _resolve_print_orientation(self, file_path: str, print_options: Dict[str, Any] = None, paper_size: Optional[str] = None) -> Optional[str]:
        """统一解析打印方向，优先用户指定，其次纸张后缀，再次文件检测"""
        opts = print_options or {}
        user_orientation = str(opts.get("orientation") or "").strip().lower()
        if user_orientation:
            if "landscape" in user_orientation or "横" in user_orientation:
                return "landscape"
            return "portrait"

        normalized_paper = str(paper_size or "").strip().lower()
        if "(横向)" in normalized_paper or "(landscape)" in normalized_paper:
            return "landscape"

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self._detect_pdf_orientation(file_path)
        return None
    
    def _detect_word_document_size(self, file_path: str) -> Optional[str]:
        """检测 Word 文档的纸张尺寸，返回标准尺寸名称"""
        try:
            import pythoncom
            from win32com import client
            
            pythoncom.CoInitialize()
            word = None
            doc = None
            
            try:
                word = client.Dispatch("Word.Application")
                word.Visible = False
                try:
                    word.DisplayAlerts = False
                except Exception:
                    pass
                
                abs_file_path = os.path.abspath(file_path)
                doc = word.Documents.Open(abs_file_path)
                
                # 获取页面设置（假设整个文档使用统一的页面设置）
                page_setup = doc.PageSetup
                page_width = page_setup.PageWidth  # 单位：点
                page_height = page_setup.PageHeight  # 单位：点
                
                doc.Close()
                word.Quit()
                
                # 转换为英寸
                width_inch = page_width / 72.0
                height_inch = page_height / 72.0
                
                # 映射到标准尺寸
                size_name = self._identify_paper_size(width_inch, height_inch)
                
                return size_name
            except Exception as e:
                print(f" [WARN] 检测 Word 文档尺寸失败：{e}")
                if word:
                    try:
                        word.Quit()
                    except Exception:
                        pass
                return None
            finally:
                pythoncom.CoUninitialize()
        except Exception as e:
            print(f" [WARN] Word 文档尺寸检测异常：{e}")
            return None
    
    def _detect_file_paper_size(self, file_path: str, print_options: Dict[str, Any] = None) -> Optional[str]:
        """根据文件类型自动检测纸张尺寸"""
        ext = os.path.splitext(file_path)[1].lower()
        
        # 如果用户已指定纸张大小，优先使用用户的设置
        if print_options:
            user_paper_size = print_options.get('paper_size') or print_options.get('page_size')
            if user_paper_size:
                logger.debug("Using user-selected paper size: %s", user_paper_size)
                return str(user_paper_size).strip()
        
        # 根据文件类型自动检测
        if ext == '.pdf':
            detected = self._detect_pdf_page_size(file_path)
            if detected:
                logger.debug("Auto-detected PDF paper size: %s", detected)
                return detected
        elif ext in ['.doc', '.docx']:
            detected = self._detect_word_document_size(file_path)
            if detected:
                logger.debug("Auto-detected Word paper size: %s", detected)
                return detected
        
        # 兜底：返回默认设置
        default_size = self._get_setting("default_paper_size") or "A4"
        logger.debug("Using default paper size: %s", default_size)
        return default_size
    
    def _resolve_image_layout_options(self, print_options: Optional[Dict[str, Any]] = None, file_path: Optional[str] = None) -> Dict[str, Any]:
        """解析图像布局选项（支持文件路径参数以自动检测纸张）"""
        options = dict(print_options or {})
        settings = self._load_settings()
        
        # 优先使用文件自身尺寸检测
        detected_paper_size = None
        if file_path and os.path.exists(file_path):
            detected_paper_size = self._detect_file_paper_size(file_path, print_options)
        
        # 如果没有检测到尺寸，使用配置或选项中的设置
        if not detected_paper_size:
            default_paper_size = settings.get("default_paper_size") or "A4"
            paper_size = options.get("paper_size") or options.get("page_size") or options.get("size") or default_paper_size
        else:
            paper_size = detected_paper_size
        
        if paper_size:
            paper_size = str(paper_size).strip()
        default_scale_mode = self._normalize_scale_mode(settings.get("default_scale_mode"), "fit")
        scale_mode = self._normalize_scale_mode(options.get("scale_mode"), default_scale_mode)
        default_max_upscale = self._safe_float(settings.get("default_max_upscale"), 3.0)
        max_upscale = self._safe_float(options.get("max_upscale"), default_max_upscale)
        if max_upscale <= 0:
            max_upscale = default_max_upscale if default_max_upscale > 0 else 3.0
        return {
            "paper_size": paper_size,
            "scale_mode": scale_mode,
            "max_upscale": max_upscale
        }

    def _calculate_scaled_size(self, src_w: int, src_h: int, dst_w: int, dst_h: int, scale_mode: str, max_upscale: float):
        if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
            return 1, 1, 1.0
        fit_scale = min(dst_w / src_w, dst_h / src_h)
        fill_scale = max(dst_w / src_w, dst_h / src_h)
        if scale_mode == "actual":
            scale = min(1.0, fit_scale)
        elif scale_mode == "fill":
            scale = fill_scale
        else:
            scale = fit_scale
        if scale_mode != "actual":
            scale = min(scale, max_upscale)
        scale = max(scale, 1.0 / max(src_w, src_h))
        return max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale))), scale

    def _find_libreoffice_path(self):
        configured = self._resolve_path(self._get_setting("libreoffice_path"))
        if configured:
            return configured
        in_path = shutil.which("soffice") or shutil.which("soffice.exe")
        if in_path and os.path.exists(in_path):
            return in_path
            
        # 检查项目目录下的 portable 文件夹 (PortableApps格式)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        portable_candidates = [
            os.path.join(current_dir, "portable", "LibreOfficePortable", "App", "libreoffice", "program", "soffice.exe"),
            os.path.join(current_dir, "portable", "App", "libreoffice", "program", "soffice.exe"),
            os.path.join(os.getcwd(), "portable", "LibreOfficePortable", "App", "libreoffice", "program", "soffice.exe"),
        ]
        
        for candidate in portable_candidates:
            if os.path.exists(candidate):
                print(f"[INFO] Found Portable LibreOffice: {candidate}")
                return candidate

        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
        candidates = [
            os.path.join(program_files, "LibreOffice", "program", "soffice.exe"),
            os.path.join(program_files_x86, "LibreOffice", "program", "soffice.exe"),
            os.path.join(program_files, "LibreOffice", "program", "soffice.com"),
            os.path.join(program_files_x86, "LibreOffice", "program", "soffice.com")
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None
    
    def _find_sumatra_pdf_path(self):
        """查找 SumatraPDF 路径"""
        # 1. 优先使用配置文件
        configured = self._resolve_path(self._get_setting("pdf_printer_path"))
        if configured:
            return configured
            
        # 2. 检查系统路径
        in_path = shutil.which("SumatraPDF") or shutil.which("SumatraPDF.exe")
        if in_path and os.path.exists(in_path):
            return in_path
            
        # 3. 检查便携版目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        portable_candidates = [
            os.path.join(current_dir, "portable", "SumatraPDF", "SumatraPDF.exe"),
            os.path.join(current_dir, "portable", "SumatraPDFPortable", "SumatraPDFPortable.exe"),
            os.path.join(current_dir, "portable", "SumatraPDFPortable", "App", "SumatraPDF", "SumatraPDF.exe"),
            os.path.join(current_dir, "portable", "SumatraPDF-3.5.2-64", "SumatraPDF-3.5.2-64.exe"),
            os.path.join(os.getcwd(), "portable", "SumatraPDF", "SumatraPDF.exe"),
        ]
        
        # 如果上述固定路径都不存在，尝试扫描portable目录
        portable_dir = os.path.join(current_dir, "portable")
        if os.path.exists(portable_dir):
            for item in os.listdir(portable_dir):
                item_path = os.path.join(portable_dir, item)
                if os.path.isdir(item_path) and "sumatra" in item.lower():
                    # 查找该目录下的可执行文件
                    for file in os.listdir(item_path):
                        if file.lower().endswith(".exe") and "sumatra" in file.lower():
                            exe_path = os.path.join(item_path, file)
                            portable_candidates.append(exe_path)
        
        for candidate in portable_candidates:
            if os.path.exists(candidate):
                print(f"[INFO] Found Portable SumatraPDF: {candidate}")
                return candidate
                
        # 4. 检查常见安装目录
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
        candidates = [
            os.path.join(program_files, "SumatraPDF", "SumatraPDF.exe"),
            os.path.join(program_files_x86, "SumatraPDF", "SumatraPDF.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def enable_printer(self, printer_name: str) -> str:
        """启用打印机"""
        return "Windows系统暂不支持此功能"
    
    def disable_printer(self, printer_name: str, reason: str = "") -> str:
        """禁用打印机"""
        return "Windows系统暂不支持此功能"
    
    def clear_print_queue(self, printer_name: str) -> str:
        """清空打印队列"""
        return "Windows系统暂不支持此功能"
    
    def remove_print_job(self, printer_name: str, job_id: str) -> str:
        """删除打印任务"""
        return "Windows系统暂不支持此功能"
    
    def discover_printers(self) -> List[Dict]:
        """发现打印机"""
        if not self.available:
            return []
        
        printers = []
        try:
            # 获取所有打印机
            printer_enum = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            
            for printer in printer_enum:
                printer_name = printer[2]  # 打印机名称
                try:
                    # 获取打印机详细信息
                    printer_handle = win32print.OpenPrinter(
                        printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE}
                    )
                    printer_info = win32print.GetPrinter(printer_handle, 2)
                    win32print.ClosePrinter(printer_handle)

                    # 判断打印机连接类型
                    printer_type = "local"
                    port_name = printer_info.get('pPortName', '')
                    if port_name:
                        if port_name.startswith('USB') or 'USB' in port_name.upper():
                            printer_type = "usb"
                        elif port_name.startswith('IP_') or 'TCP' in port_name.upper():
                            printer_type = "network"
                        elif port_name.startswith('LPT') or port_name.startswith('COM'):
                            printer_type = "local"

                    # 获取实际状态
                    actual_status = self.get_printer_status(printer_name)
                    
                    printers.append({
                        "name": printer_name,
                        "type": printer_type,
                        "location": printer_info.get('pLocation', ''),
                        "make_model": printer_info.get('pDriverName', ''),
                        "status": actual_status
                    })
                except Exception as e:
                    print(f"获取打印机 {printer_name} 信息失败: {e}")
                    printers.append({
                        "name": printer_name,
                        "type": "unknown",
                        "location": "",
                        "make_model": "",
                        "status": "error"
                    })
        except Exception as e:
            print(f"枚举打印机失败: {e}")
        
        return printers
    
    def get_printer_status(self, printer_name: str) -> str:
        """获取打印机状态"""
        detail = self.get_printer_status_detail(printer_name)
        return detail.get("status_text", "未知")

    def get_printer_status_detail(self, printer_name: str) -> Dict[str, Any]:
        """获取打印机状态详情（包含原始状态码）"""
        if not self.available:
            return {
                "status_text": "Windows打印API不可用",
                "win32_status": None,
                "win32_attributes": None,
                "wmi": None,
            }
        
        try:
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            printer_info = win32print.GetPrinter(printer_handle, 2)
            win32print.ClosePrinter(printer_handle)
            
            status = printer_info.get('Status', 0)
            attributes = printer_info.get('Attributes', 0)
            wmi_detail = self._get_wmi_printer_status_detail(printer_name)
            
            # 首先检查是否设置为离线工作
            # PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400
            if attributes & 0x00000400:
                return {
                    "status_text": "离线",
                    "win32_status": status,
                    "win32_attributes": attributes,
                    "wmi": wmi_detail,
                }
            
            # 然后根据状态值判断
            status_text = self._get_printer_status_text(status)
            wmi_status_text = wmi_detail.get("status_text") if wmi_detail else None
            if wmi_status_text:
                status_text = wmi_status_text
            elif status == 0:
                # WMI 不可用且 Win32 Status bitmask 为 0（"就绪"）。
                # 对于网络打印机，Win32 Status 经常为 0 但打印机实际有
                # 硬件问题。PRINTER_INFO_3 包含 spooler 维护的独立状态
                # 字符串，可提供额外的信息。
                result_dict = {"status_text": status_text}
                self._enrich_status_from_printer_info_3(printer_name, result_dict=result_dict)
                status_text = result_dict["status_text"]

            return {
                "status_text": status_text,
                "win32_status": status,
                "win32_attributes": attributes,
                "wmi": wmi_detail,
            }
                
        except Exception as e:
            return {
                "status_text": f"获取状态失败: {e}",
                "win32_status": None,
                "win32_attributes": None,
                "wmi": None,
            }
    
    def get_print_queue(self, printer_name: str) -> List[Dict]:
        """获取打印队列"""
        if not self.available:
            return []
        
        jobs = []
        try:
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            job_enum = win32print.EnumJobs(printer_handle, 0, -1, 1)
            win32print.ClosePrinter(printer_handle)
            
            for job in job_enum:
                jobs.append({
                    "id": str(job['JobId']),
                    "document": job.get('pDocument', ''),
                    "user": job.get('pUserName', ''),
                    "status": self._get_job_status_text(job.get('Status', 0)),
                    "pages": job.get('PagesPrinted', 0),
                    "size": job.get('Size', 0)
                })
        except Exception as e:
            print(f"获取打印队列失败: {e}")
        
        return jobs
    
    def get_job_status(self, printer_name: str, job_id: int) -> Dict[str, Any]:
        """获取特定打印任务的状态"""
        if not self.available:
            return {"exists": False, "status": "unknown"}
        
        try:
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
            win32print.ClosePrinter(printer_handle)
            
            for job in jobs:
                if job["JobId"] == job_id:
                    return {
                        "exists": True,
                        "status": self._get_job_status_text(job["Status"]),
                        "pages_printed": job["PagesPrinted"],
                        "total_pages": job["TotalPages"]
                    }
            
            # 如果在队列中找不到任务，说明任务已完成或失败
            return {"exists": False, "status": "completed_or_failed"}
        except Exception as e:
            print(f"获取任务状态失败: {e}")
            return {"exists": False, "status": "error"}
    
    def _resolve_windows_printer_queue(self, printer_name: str) -> Optional[Dict[str, Any]]:
        """Resolve a cloud/display printer name to one exact Windows spooler queue."""
        if not self.available or not printer_name:
            return None

        try:
            printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
        except Exception as e:
            logger.warning(
                "job_id_debug enum_printers_error requested=%r error=%s",
                printer_name,
                e,
            )
            return None

        candidates = []
        for item in printers:
            if len(item) > 2 and item[2]:
                candidates.append({"name": item[2], "driver": "", "port": ""})

        requested = str(printer_name).strip()
        requested_key = requested.casefold()

        def pick_unique(matches: List[Dict[str, Any]], tag: str) -> Optional[Dict[str, Any]]:
            if len(matches) == 1:
                resolved = self._get_windows_printer_queue_detail(matches[0]["name"])
                logger.debug(
                    "job_id_debug printer_resolved tag=%s requested=%r resolved=%r driver=%r port=%r",
                    tag,
                    printer_name,
                    resolved.get("name"),
                    resolved.get("driver"),
                    resolved.get("port"),
                )
                return resolved
            if len(matches) > 1:
                logger.warning(
                    "job_id_debug ambiguous_printer_name tag=%s requested=%r candidates=%s",
                    tag,
                    printer_name,
                    [
                        {
                            "name": item.get("name"),
                            "driver": item.get("driver"),
                            "port": item.get("port"),
                        }
                        for item in matches
                    ],
                )
                return None
            return None

        exact = [item for item in candidates if item["name"] == requested]
        resolved = pick_unique(exact, "exact")
        if resolved:
            return resolved

        casefold = [item for item in candidates if item["name"].casefold() == requested_key]
        resolved = pick_unique(casefold, "casefold")
        if resolved:
            return resolved

        logger.warning(
            "job_id_debug printer_name_not_found requested=%r candidates=%s",
            printer_name,
            [
                {
                    "name": item.get("name"),
                    "driver": item.get("driver"),
                    "port": item.get("port"),
                }
                for item in candidates
            ],
        )
        return None

    def _get_windows_printer_queue_detail(self, queue_name: str) -> Dict[str, Any]:
        detail = {"name": queue_name, "driver": "", "port": ""}
        handle = None
        try:
            handle = win32print.OpenPrinter(
                queue_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE}
            )
            info = win32print.GetPrinter(handle, 2)
            detail["driver"] = info.get("pDriverName", "")
            detail["port"] = info.get("pPortName", "")
        except Exception as e:
            detail["error"] = str(e)
        finally:
            if handle:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    logger.debug("Closing printer handle failed", exc_info=True)
        return detail

    def _enum_print_jobs_raw(self, printer_name: str) -> List[Dict[str, Any]]:
        handle = None
        try:
            handle = win32print.OpenPrinter(
                printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE}
            )
            return list(win32print.EnumJobs(handle, 0, -1, 1) or [])
        except ModuleNotFoundError as e:
            logger.warning(
                "job_id_debug enum_jobs_error printer=%r missing_module=%r error=%s",
                printer_name,
                getattr(e, "name", None) or str(e),
                e,
            )
            raise
        except Exception as e:
            logger.warning(
                "job_id_debug enum_jobs_error printer=%r error=%s",
                printer_name,
                e,
            )
            raise
        finally:
            if handle:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    logger.debug("Closing printer handle failed", exc_info=True)

    def _summarize_print_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "JobId": job.get("JobId"),
                "pDocument": job.get("pDocument", ""),
                "Status": job.get("Status"),
            }
            for job in jobs
        ]

    def _document_matches_job_name(self, document_name: str, job_name: Optional[str]) -> bool:
        if not job_name:
            return True
        document = os.path.basename(str(document_name or "")).casefold()
        expected = os.path.basename(str(job_name or "")).casefold()
        return bool(document and expected and document == expected)

    def _prepare_print_job_tracking(
        self, printer_name: str, job_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        resolved = self._resolve_windows_printer_queue(printer_name)
        if not resolved:
            return None

        queue_name = resolved["name"]
        try:
            before_jobs = self._enum_print_jobs_raw(queue_name)
        except Exception:
            return None

        before_ids = {job.get("JobId") for job in before_jobs if job.get("JobId") is not None}
        logger.debug(
            "job_id_debug queue_snapshot_before printer=%r resolved=%r job_name=%r jobs=%s",
            printer_name,
            queue_name,
            job_name,
            self._summarize_print_jobs(before_jobs),
        )
        return {
            "requested_name": printer_name,
            "queue_name": queue_name,
            "driver": resolved.get("driver", ""),
            "port": resolved.get("port", ""),
            "before_job_ids": before_ids,
            "before_jobs": before_jobs,
        }

    def _get_latest_job_id(
        self,
        printer_name: str,
        job_name: str = None,
        max_wait: float = 5.0,
        before_job_ids: Optional[set] = None,
    ) -> Optional[int]:
        """Return a unique matching Windows spooler job id; never guess by latest id."""
        if not self.available:
            return None

        import time

        resolved = self._resolve_windows_printer_queue(printer_name)
        if not resolved:
            return None

        queue_name = resolved["name"]
        before_ids = set(before_job_ids or set())
        attempts = max(1, int(max_wait * 10))

        last_reason = "no_new_job"
        for attempt in range(attempts):
            try:
                jobs = self._enum_print_jobs_raw(queue_name)
            except ModuleNotFoundError:
                logger.warning(
                    "job_id_debug enum_jobs_error printer=%r resolved=%r job_name=%r before_job_ids=%s max_wait=%.1fs",
                    printer_name,
                    queue_name,
                    job_name,
                    sorted(before_ids),
                    max_wait,
                )
                return None
            except Exception:
                last_reason = "enum_jobs_error"
                time.sleep(0.1)
                continue

            new_jobs = [
                job for job in jobs
                if job.get("JobId") is not None and job.get("JobId") not in before_ids
            ]
            matching_jobs = [
                job for job in new_jobs
                if self._document_matches_job_name(job.get("pDocument", ""), job_name)
            ]

            logger.debug(
                "job_id_debug queue_poll attempt=%s printer=%r resolved=%r job_name=%r jobs=%s new_jobs=%s matching_jobs=%s",
                attempt + 1,
                printer_name,
                queue_name,
                job_name,
                self._summarize_print_jobs(jobs),
                self._summarize_print_jobs(new_jobs),
                self._summarize_print_jobs(matching_jobs),
            )

            if len(matching_jobs) == 1:
                job_id = matching_jobs[0].get("JobId")
                logger.info(
                    "job_id_debug job_id_matched printer=%r resolved=%r job_id=%s document=%r",
                    printer_name,
                    queue_name,
                    job_id,
                    matching_jobs[0].get("pDocument", ""),
                )
                return job_id

            if len(matching_jobs) > 1:
                last_reason = "multiple_new_jobs"
                logger.warning(
                    "job_id_debug multiple_new_jobs printer=%r resolved=%r job_name=%r matches=%s",
                    printer_name,
                    queue_name,
                    job_name,
                    self._summarize_print_jobs(matching_jobs),
                )
                return None

            if new_jobs:
                last_reason = "document_name_mismatch"
                logger.warning(
                    "job_id_debug document_name_mismatch printer=%r resolved=%r job_name=%r new_jobs=%s",
                    printer_name,
                    queue_name,
                    job_name,
                    self._summarize_print_jobs(new_jobs),
                )
            else:
                last_reason = "no_new_job"

            time.sleep(0.1)

        logger.warning(
            "job_id_debug %s printer=%r resolved=%r job_name=%r before_job_ids=%s max_wait=%.1fs",
            last_reason,
            printer_name,
            queue_name,
            job_name,
            sorted(before_ids),
            max_wait,
        )
        return None
    
    def _get_job_status_text(self, status: int) -> str:
        """获取任务状态文本"""
        status_map = {
            0x00000001: "暂停",
            0x00000002: "错误",
            0x00000004: "正在删除",
            0x00000008: "正在后台处理",
            0x00000010: "正在打印",
            0x00000020: "离线",
            0x00000040: "缺纸",
            0x00000080: "已打印",
            0x00000100: "已删除",
            0x00000200: "被阻止",
            0x00000400: "用户干预",
            0x00000800: "重新启动"
        }
        
        for flag, text in status_map.items():
            if status & flag:
                return text
        return "未知"
    
    def submit_print_job(self, printer_name: str, file_path: str, job_name: str = "", print_options: Dict[str, str] = None, printer_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """提交打印任务，返回任务信息
        
        Args:
            printer_name: 打印机名称
            file_path: 文件路径
            job_name: 任务名称
            print_options: 打印选项
            printer_config: 打印机配置信息（保留参数，当前不使用）
        """
        if not self.available:
            return {"success": False, "message": "Windows打印API不可用"}
        
        try:
            resolved = self._resolve_windows_printer_queue(printer_name)
            if not resolved:
                logger.warning("System printer missing: %s", printer_name)
                return {"success": False, "message": f"打印机 {printer_name} 未安装到Windows系统，无法提交到打印队列"}
            queue_printer_name = resolved["name"]
            logger.info("System printer available: %s", queue_printer_name)
            
            logger.debug("Using system print path with print options support")
            
            # 检查文件类型（系统打印路径）
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']:
                # 图片文件使用GDI打印
                return self._print_image_file(queue_printer_name, file_path, job_name, print_options)
            elif file_ext == '.pdf':
                # PDF文件尝试调用系统打印
                return self._print_pdf_file(queue_printer_name, file_path, job_name, print_options)
            elif file_ext in ['.doc', '.docx']:
                # Word文档先转PDF再打印
                return self._print_word_file(queue_printer_name, file_path, job_name, print_options)
            else:
                # 文本文件使用RAW打印
                return self._print_raw_file(queue_printer_name, file_path, job_name, print_options)
                
        except Exception as e:
            logger.exception("Submitting print job failed")
            return {"success": False, "message": f"提交打印任务失败: {e}"}

    def _print_word_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """将Word文档转换为PDF后打印"""
        import tempfile
        import os
        import pythoncom
        from win32com import client
        import subprocess
        from portable_temp import get_portable_temp_dir
        
        pdf_path = None
        try:
            # 初始化COM库（多线程环境下必需）
            pythoncom.CoInitialize()
            
            # 使用 portable temp 目录
            temp_dir = get_portable_temp_dir()
            pdf_filename = f"{os.path.splitext(os.path.basename(file_path))[0]}.pdf"
            pdf_path = os.path.join(temp_dir, pdf_filename)
            
            # 如果临时PDF已存在，先删除
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except:
                    pass
            
            print(f" [INFO] 正在将Word文档转换为PDF: {file_path} -> {pdf_path}")

            abs_file_path = os.path.abspath(file_path)

            def convert_with_com(prog_id: str) -> bool:
                word = None
                doc = None
                try:
                    word = client.Dispatch(prog_id)
                    word.Visible = False
                    try:
                        word.DisplayAlerts = False
                    except:
                        pass
                    doc = word.Documents.Open(abs_file_path)
                    doc.SaveAs(pdf_path, FileFormat=17)
                    doc.Close()
                    print(f" [INFO] 文档转PDF成功 (使用 {prog_id})")
                    return True
                except Exception as e:
                    print(f" [WARNING] 文档转PDF失败 ({prog_id}): {e}")
                    try:
                        if doc:
                            doc.Close()
                    except:
                        pass
                    return False
                finally:
                    try:
                        if word:
                            word.Quit()
                    except:
                        pass

            wps_prog_ids = ["Kwps.Application", "WPS.Application", "wps.application"]
            for prog_id in wps_prog_ids:
                if convert_with_com(prog_id):
                    result = self._print_pdf_file(printer_name, pdf_path, job_name, print_options)
                    # 添加转换后的文件路径，以便后续清理
                    if result.get("success"):
                        result["converted_file"] = pdf_path
                    return result

            soffice = self._find_libreoffice_path()
            if soffice:
                try:
                    result = subprocess.run(
                        [soffice, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, abs_file_path],
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                    )
                    if result.returncode == 0 and os.path.exists(pdf_path):
                        print(" [INFO] 文档转PDF成功 (使用 LibreOffice)")
                        pdf_result = self._print_pdf_file(printer_name, pdf_path, job_name, print_options)
                        # 添加转换后的文件路径，以便后续清理
                        if pdf_result.get("success"):
                            pdf_result["converted_file"] = pdf_path
                        return pdf_result
                except Exception as e:
                    print(f" [WARNING] 文档转PDF失败 (LibreOffice): {e}")

            if convert_with_com("Word.Application"):
                result = self._print_pdf_file(printer_name, pdf_path, job_name, print_options)
                # 添加转换后的文件路径，以便后续清理
                if result.get("success"):
                    result["converted_file"] = pdf_path
                return result

            return {"success": False, "message": "文档转PDF失败，未找到可用的文档处理程序"}
            
        except Exception as e:
            print(f" [ERROR] 处理Word文档失败: {e}")
            return {"success": False, "message": f"Word文档处理失败: {str(e)}"}
        finally:
            # 清理COM库
            pythoncom.CoUninitialize()

    def _configure_printer_devmode(self, printer_name: str, print_options: Dict[str, str]) -> bool:
        """配置打印机DEVMODE（在打印前设置打印参数）"""
        try:
            import win32print
            import win32con
            import pywintypes
            
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            try:
                # 获取当前DEVMODE
                properties = win32print.GetPrinter(printer_handle, 2)
                devmode = properties['pDevMode']
                
                if not devmode:
                    print(f" [WARNING] 无法获取打印机DEVMODE，跳过配置")
                    return False
                
                print(f" [INFO] 开始配置打印机参数...")
                
                # 打印当前打印机能力（首次调试）
                self._log_printer_capabilities(printer_handle, devmode)
                
                # 检查打印机支持的功能
                fields = devmode.Fields
                supports_duplex = bool(fields & win32con.DM_DUPLEX)
                supports_color = bool(fields & win32con.DM_COLOR)
                
                # 设置双面打印（仅在支持时）
                if 'duplex' in print_options and supports_duplex:
                    duplex_value = print_options['duplex']
                    print(f"   双面打印: {duplex_value}")
                    duplex_map = {
                        'None': win32con.DMDUP_SIMPLEX,
                        'simplex': win32con.DMDUP_SIMPLEX,
                        'single': win32con.DMDUP_SIMPLEX,  # 云端传来的单面值
                        'DuplexNoTumble': win32con.DMDUP_VERTICAL,
                        'DuplexTumble': win32con.DMDUP_HORIZONTAL,
                        'LongEdge': win32con.DMDUP_VERTICAL,
                        'ShortEdge': win32con.DMDUP_HORIZONTAL,
                        'long': win32con.DMDUP_VERTICAL,
                        'short': win32con.DMDUP_HORIZONTAL,
                    }
                    if duplex_value in duplex_map:
                        devmode.Duplex = duplex_map[duplex_value]
                        devmode.Fields |= win32con.DM_DUPLEX
                        print(f"   已设置双面模式: {duplex_value} -> {duplex_map[duplex_value]}")
                elif 'duplex' in print_options and not supports_duplex:
                    print(f"   打印机不支持双面打印功能，跳过该设置")
                
                # 设置色彩模式（仅在支持时）
                color_value = print_options.get('color_mode') or print_options.get('color_model')
                if color_value and supports_color:
                    print(f"   色彩模式: {color_value}")
                    color_str = str(color_value).lower()
                    if color_str in ['gray', 'grayscale', 'mono', 'monochrome', 'black']:
                        devmode.Color = win32con.DMCOLOR_MONOCHROME
                        print(f"   已设置黑白打印 (DMCOLOR_MONOCHROME={win32con.DMCOLOR_MONOCHROME})")
                    else:
                        devmode.Color = win32con.DMCOLOR_COLOR
                        print(f"   已设置彩色打印 (DMCOLOR_COLOR={win32con.DMCOLOR_COLOR})")
                    devmode.Fields |= win32con.DM_COLOR
                elif color_value and not supports_color:
                    print(f"   打印机不支持色彩模式设置，跳过该设置")
                
                # 设置纸张大小（支持 "Letter (横向)" 等规范化）
                if 'paper_size' in print_options:
                    paper_size = self._normalize_paper_size_for_win32(print_options['paper_size'])
                    paper_size_map = {
                        'A4': win32con.DMPAPER_A4,
                        'A3': win32con.DMPAPER_A3,
                        'A5': win32con.DMPAPER_A5,
                        'Letter': win32con.DMPAPER_LETTER,
                        'Legal': win32con.DMPAPER_LEGAL,
                    }
                    if paper_size and paper_size in paper_size_map:
                        devmode.PaperSize = paper_size_map[paper_size]
                        devmode.Fields |= win32con.DM_PAPERSIZE
                        print(f"   已设置纸张: {paper_size}")
                
                # 设置份数
                if 'copies' in print_options:
                    try:
                        copies_int = int(print_options['copies'])
                        if copies_int > 0:
                            devmode.Copies = copies_int
                            devmode.Fields |= win32con.DM_COPIES
                            print(f"   已设置份数: {copies_int}")
                    except (ValueError, TypeError):
                        pass
                
                # 应用DEVMODE（使用DocumentProperties API，避免权限问题）
                try:
                    # 方法1：使用SetPrinter（需要管理员权限）
                    properties['pDevMode'] = devmode
                    win32print.SetPrinter(printer_handle, 2, properties, 0)
                    print(f" [INFO] 打印机参数配置完成 (SetPrinter)")
                    return True
                except pywintypes.error as e:
                    if e.args[0] == 5:  # 拒绝访问
                        print(f"   SetPrinter拒绝访问，使用DocumentProperties API...")
                        # 方法2：使用DocumentProperties（不需要管理员权限，仅对当前打印任务生效）
                        try:
                            import win32gui
                            # DocumentProperties会修改devmode并返回
                            # DM_IN_BUFFER | DM_OUT_BUFFER = 2 | 8 = 10
                            result_devmode = win32print.DocumentProperties(
                                0,  # hWnd
                                printer_handle,
                                printer_name,
                                devmode,  # pDevModeInput
                                devmode,  # pDevModeOutput
                                win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
                            )
                            print(f" [INFO] 打印机参数配置完成 (DocumentProperties)")
                            return True
                        except Exception as doc_err:
                            print(f"   DocumentProperties也失败: {doc_err}")
                            raise
                    else:
                        raise
                
            finally:
                win32print.ClosePrinter(printer_handle)
                
        except Exception as e:
            print(f" [WARNING] 配置打印机DEVMODE失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def _log_printer_capabilities(self, printer_handle, devmode):
        """记录打印机能力（用于调试）"""
        try:
            import win32con
            print(f"   打印机当前能力:")
            
            # 基本信息
            if hasattr(devmode, 'DriverVersion'):
                print(f"    - 驱动版本: {devmode.DriverVersion}")
            if hasattr(devmode, 'DeviceName'):
                print(f"    - 设备名称: {devmode.DeviceName}")
            
            # 当前设置
            if hasattr(devmode, 'Duplex'):
                duplex_names = {1: "单面(SIMPLEX)", 2: "长边双面(VERTICAL)", 3: "短边双面(HORIZONTAL)"}
                print(f"    - 当前双面: {devmode.Duplex} ({duplex_names.get(devmode.Duplex, '未知')})")
            if hasattr(devmode, 'Color'):
                color_names = {1: "单色(MONOCHROME)", 2: "彩色(COLOR)"}
                print(f"    - 当前色彩: {devmode.Color} ({color_names.get(devmode.Color, '未知')})")
            if hasattr(devmode, 'PaperSize'):
                print(f"    - 当前纸张: {devmode.PaperSize}")
            if hasattr(devmode, 'Copies'):
                print(f"    - 当前份数: {devmode.Copies}")
                
            # 支持的能力（通过Fields标志判断）
            if hasattr(devmode, 'Fields'):
                fields = devmode.Fields
                print(f"    - Fields标志: {hex(fields)}")
                print(f"    - 支持的功能:")
                
                supported = []
                if fields & win32con.DM_ORIENTATION:
                    supported.append("方向(ORIENTATION)")
                if fields & win32con.DM_PAPERSIZE:
                    supported.append("纸张大小(PAPERSIZE)")
                if fields & win32con.DM_PAPERLENGTH:
                    supported.append("纸张长度(PAPERLENGTH)")
                if fields & win32con.DM_PAPERWIDTH:
                    supported.append("纸张宽度(PAPERWIDTH)")
                if fields & win32con.DM_COPIES:
                    supported.append("份数(COPIES)")
                if fields & win32con.DM_DEFAULTSOURCE:
                    supported.append("纸张来源(DEFAULTSOURCE)")
                if fields & win32con.DM_PRINTQUALITY:
                    supported.append("打印质量(PRINTQUALITY)")
                if fields & win32con.DM_COLOR:
                    supported.append(" 色彩模式(COLOR)")
                if fields & win32con.DM_DUPLEX:
                    supported.append(" 双面打印(DUPLEX)")
                if fields & win32con.DM_YRESOLUTION:
                    supported.append("Y分辨率(YRESOLUTION)")
                if fields & win32con.DM_TTOPTION:
                    supported.append("TrueType选项(TTOPTION)")
                if fields & win32con.DM_COLLATE:
                    supported.append("逐份打印(COLLATE)")
                
                for feature in supported:
                    print(f"       {feature}")
                    
        except Exception as e:
            print(f"     无法读取打印机能力: {e}")
    
    def _print_pdf_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """打印PDF文件 (使用ShellExecute调用默认PDF阅读器打印)"""
        import win32api
        import win32print
        import subprocess
        
        print(f"[INFO] 开始打印PDF: {file_path} -> {printer_name}")
        
        try:
            abs_path = os.path.abspath(file_path)

            # 选择PDF打印引擎：sumatra / system / auto(默认)
            pdf_engine = "auto"
            if print_options and print_options.get("pdf_engine"):
                pdf_engine = str(print_options.get("pdf_engine", "auto")).strip().lower()
            elif self._get_setting("pdf_engine"):
                pdf_engine = str(self._get_setting("pdf_engine", "auto")).strip().lower()

            effective_engine = "sumatra" if pdf_engine == "auto" else pdf_engine

            force_bitmap_engine = effective_engine in ["bitmap", "bitmap_gdi", "raster", "image"]
            prefer_system_engine = (effective_engine == "system")

            if force_bitmap_engine:
                print("[INFO] 使用位图引擎打印PDF")
                return self._print_pdf_file_bitmap(printer_name, abs_path, job_name, print_options or {})
            
            # 使用自动发现逻辑
            sumatra_path = self._find_sumatra_pdf_path()
            
            if not prefer_system_engine and not sumatra_path:
                return {"success": False, "message": "SumatraPDF不可用，未提交打印任务", "job_id": None}

            if sumatra_path and not prefer_system_engine:
                try:
                    print(f"[INFO] 使用 SumatraPDF 打印：{sumatra_path}")
                    tracking = self._prepare_print_job_tracking(
                        printer_name, os.path.basename(abs_path)
                    )
                    if not tracking:
                        return {
                            "success": False,
                            "message": "无法解析Windows打印队列，无法追踪本地打印任务ID",
                            "job_id": None,
                        }
                    queue_printer_name = tracking["queue_name"]
                    logger.info(
                        "job_id_debug print_submit cloud_printer=%r resolved=%r driver=%r port=%r document=%r",
                        printer_name,
                        queue_printer_name,
                        tracking.get("driver"),
                        tracking.get("port"),
                        os.path.basename(abs_path),
                    )
                                
                    # 在打印前先配置打印机的纸张设置（关键修复！）
                    # 仅调用一次 _detect_file_paper_size，避免重复检测
                    detected_paper_size = self._detect_file_paper_size(abs_path, print_options)
                    if detected_paper_size:
                        print(f" [INFO] 检测到纸张尺寸：{detected_paper_size}，配置打印机...")
                        config_options = dict(print_options or {})
                        config_options['paper_size'] = detected_paper_size
                        self._configure_printer_devmode(queue_printer_name, config_options)
                                
                    cmd = [sumatra_path, "-print-to", queue_printer_name, "-silent", "-exit-when-done"]
                    
                    # 构建打印设置字符串
                    print_settings = []
                    
                    if print_options:
                        duplex_value = print_options.get("duplex")
                        if duplex_value in ["DuplexNoTumble", "LongEdge", "long", "long_edge"]:
                            print_settings.append("duplexlong")
                        elif duplex_value in ["DuplexTumble", "ShortEdge", "short", "short_edge"]:
                            print_settings.append("duplexshort")
                        elif duplex_value in ["None", "none", "simplex", "single"]:
                            print_settings.append("simplex")
                        
                        color_value = print_options.get("color_mode") or print_options.get("color_model")
                        if color_value:
                            color_str = str(color_value).lower()
                            if color_str in ["grayscale", "gray", "mono", "monochrome", "black"]:
                                print_settings.append("monochrome")
                            elif color_str in ["color", "colour", "rgb"]:
                                print_settings.append("color")
                        
                        copies = print_options.get("copies")
                        if copies:
                            try:
                                copies_int = int(copies)
                                if copies_int > 1:
                                    print_settings.append(f"{copies_int}x")
                            except (ValueError, TypeError):
                                pass
                    
                    # 使用已检测的纸张尺寸，规范化 "Letter (横向)" 等
                    paper_str = self._normalize_paper_size_for_win32(detected_paper_size)
                    if paper_str:
                        paper_str = paper_str.upper()
                        if paper_str in ["A4", "A3", "A5", "LETTER", "LEGAL", "TABLOID"]:
                            print(f" [INFO] SumatraPDF 使用纸张：{paper_str}")
                            # SumatraPDF 纸张参数格式必须是 paper=<size>，否则可能被忽略并回退为自定义纸张
                            print_settings.append(f"paper={paper_str}")
                    # 锁定方向，避免 Sumatra/驱动自动旋转导致预览与实打不一致
                    orientation = self._resolve_print_orientation(abs_path, print_options or {}, detected_paper_size)
                    if orientation in ["portrait", "landscape"]:
                        print(f" [INFO] SumatraPDF 锁定方向：{orientation}")
                        print_settings.append(orientation)
                    # 统一添加 fit，确保所有纸张内容完整适配、避免截断
                    if "fit" not in print_settings:
                        print_settings.append("fit")

                    print_settings_str = ",".join(print_settings)
                    if print_settings_str:
                        print(f"[INFO] SumatraPDF print-settings: {print_settings_str}")
                        cmd.extend(["-print-settings", print_settings_str])
                    
                    cmd.append(abs_path)
                    logger.info(
                        "job_id_debug sumatra_command printer=%r executable=%r document=%r settings=%r",
                        queue_printer_name,
                        os.path.basename(sumatra_path),
                        os.path.basename(abs_path),
                        print_settings_str,
                    )
                    logger.debug(
                        "job_id_debug sumatra_command_full printer=%r cmd=%s",
                        queue_printer_name,
                        cmd,
                    )
                    result = subprocess.run(
                        cmd,
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                    )
                    logger.info(
                        "job_id_debug sumatra_result printer=%r returncode=%s stdout=%r stderr=%r",
                        queue_printer_name,
                        result.returncode,
                        (result.stdout or "").strip()[:500],
                        (result.stderr or "").strip()[:500],
                    )
                    if result.returncode != 0:
                        return {"success": False, "message": f"SumatraPDF打印失败: {result.stderr.strip() or result.stdout.strip()}"}
                    print(f"[INFO] SumatraPDF 打印成功 (exitCode: {result.returncode})")
                    
                    job_id = self._get_latest_job_id(
                        queue_printer_name,
                        os.path.basename(abs_path),
                        before_job_ids=tracking["before_job_ids"],
                    )
                    if job_id:
                        print(f"[INFO] 获取到打印任务ID: {job_id}")
                    else:
                        print("[WARN] 无法获取本地打印任务ID")
                        return {
                            "success": False,
                            "message": "无法获取本地打印任务ID",
                            "job_id": None,
                        }
                    
                    return {
                        "success": True,
                        "message": "SumatraPDF 打印任务已提交",
                        "job_id": job_id,
                        "printer_name": queue_printer_name,
                    }
                except Exception as e:
                    return {"success": False, "message": f"SumatraPDF打印失败: {str(e)}"}

            if prefer_system_engine:
                reason = "配置指定" if effective_engine == "system" else "按配置走系统引擎"
                print(f"[INFO] 使用系统打印引擎 (printto/print): {reason}")
            
            # system engine uses printto only; it never changes the default printer.
            tracking = self._prepare_print_job_tracking(
                printer_name, os.path.basename(abs_path)
            )
            if not tracking:
                return {
                    "success": False,
                    "message": "无法解析Windows打印队列，无法追踪本地打印任务ID",
                    "job_id": None,
                }
            queue_printer_name = tracking["queue_name"]
            logger.info(
                "job_id_debug print_submit cloud_printer=%r resolved=%r driver=%r port=%r document=%r",
                printer_name,
                queue_printer_name,
                tracking.get("driver"),
                tracking.get("port"),
                os.path.basename(abs_path),
            )
            res = 33
            print(f"[INFO] 尝试使用 'printto' 动词打印: {abs_path}")
            res = win32api.ShellExecute(0, "printto", abs_path, f'"{queue_printer_name}"', ".", 0)
            
            if res <= 32:
                return {"success": False, "message": f"printto 调用失败, 错误码: {res}"}
            
            job_id = self._get_latest_job_id(
                queue_printer_name,
                os.path.basename(abs_path),
                before_job_ids=tracking["before_job_ids"],
            )
            if not job_id:
                print("[WARN] 无法获取本地打印任务ID")
                return {
                    "success": False,
                    "message": "无法获取本地打印任务ID",
                    "job_id": None,
                }
            
            return {
                "success": True, 
                "job_id": job_id, 
                "printer_name": queue_printer_name,
                "file_path": file_path,
                "message": "PDF打印命令已发送"
            }
            
        except Exception as e:
            print(f"[ERROR] PDF打印失败: {e}")
            return {"success": False, "message": f"PDF打印失败: {str(e)}"}

    def _print_pdf_file_bitmap(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        printer_handle = None
        hdc = None
        document = None
        try:
            import fitz
            import win32ui
            import win32con
            import win32gui
            from PIL import Image
            from portable_temp import get_temp_file_path
            import time

            options = print_options or {}
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            devmode = None

            try:
                devmode = win32print.GetPrinter(printer_handle, 2)['pDevMode']
                if not devmode:
                    devmode = pywintypes.DEVMODEType()
                    devmode.DeviceName = printer_name
            except Exception:
                devmode = None

            if devmode:
                # 优先使用文件自身的纸张尺寸（支持 "Letter (横向)" 等）
                paper_size = self._detect_file_paper_size(file_path, options)
                if paper_size:
                    paper_key = self._normalize_paper_size_for_win32(paper_size)
                    if paper_key:
                        paper_key = paper_key.upper()
                        paper_size_map = {
                            'A4': win32con.DMPAPER_A4,
                            'LETTER': win32con.DMPAPER_LETTER,
                            'LEGAL': win32con.DMPAPER_LEGAL,
                            'A3': win32con.DMPAPER_A3,
                            'A5': win32con.DMPAPER_A5
                        }
                        if paper_key in paper_size_map:
                            print(f" [INFO] 位图打印使用检测到的纸张：{paper_size}")
                            devmode.PaperSize = paper_size_map[paper_key]
                            devmode.Fields |= win32con.DM_PAPERSIZE

                duplex_value = options.get('duplex')
                duplex_map = {
                    'None': win32con.DMDUP_SIMPLEX,
                    'none': win32con.DMDUP_SIMPLEX,
                    'simplex': win32con.DMDUP_SIMPLEX,
                    'DuplexNoTumble': win32con.DMDUP_VERTICAL,
                    'LongEdge': win32con.DMDUP_VERTICAL,
                    'long': win32con.DMDUP_VERTICAL,
                    'long_edge': win32con.DMDUP_VERTICAL,
                    'DuplexTumble': win32con.DMDUP_HORIZONTAL,
                    'ShortEdge': win32con.DMDUP_HORIZONTAL,
                    'short': win32con.DMDUP_HORIZONTAL,
                    'short_edge': win32con.DMDUP_HORIZONTAL
                }
                if duplex_value in duplex_map:
                    devmode.Duplex = duplex_map[duplex_value]
                    devmode.Fields |= win32con.DM_DUPLEX

                color_value = options.get('color_mode') or options.get('color_model')
                if color_value:
                    color_str = str(color_value).lower()
                    devmode.Color = win32con.DMCOLOR_MONOCHROME if color_str in ['gray', 'grayscale', 'mono', 'monochrome', 'black'] else win32con.DMCOLOR_COLOR
                    devmode.Fields |= win32con.DM_COLOR

                copies = options.get('copies')
                if copies:
                    try:
                        copies_int = int(copies)
                        if copies_int > 0:
                            devmode.Copies = copies_int
                            devmode.Fields |= win32con.DM_COPIES
                    except (ValueError, TypeError):
                        pass

            if devmode:
                h_printer_dc = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
                hdc = win32ui.CreateDCFromHandle(h_printer_dc)
            else:
                hdc = win32ui.CreateDC()
                hdc.CreatePrinterDC(printer_name)

            dpi_setting = options.get("pdf_bitmap_dpi") or self._get_setting("pdf_bitmap_dpi", 300)
            try:
                render_dpi = max(150, min(600, int(dpi_setting)))
            except (ValueError, TypeError):
                render_dpi = 300

            zoom = render_dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            document = fitz.open(file_path)
            page_count = len(document)
            if page_count <= 0:
                return {"success": False, "message": "PDF无可打印页面"}

            job_id = hdc.StartDoc(job_name or os.path.basename(file_path))
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                temp_bmp = get_temp_file_path(prefix=f"pdf_page_{page_index+1}_", suffix=".bmp")
                img.save(temp_bmp, "BMP")

                hbmp = None
                mem_dc = None
                old_bmp = None
                try:
                    hdc.StartPage()
                    printer_width = hdc.GetDeviceCaps(win32con.HORZRES)
                    printer_height = hdc.GetDeviceCaps(win32con.VERTRES)

                    img_width, img_height = img.size
                    fit_scale = min(printer_width / img_width, printer_height / img_height)
                    scale = min(1.0, fit_scale)
                    draw_width = max(1, int(img_width * scale))
                    draw_height = max(1, int(img_height * scale))
                    x_offset = (printer_width - draw_width) // 2
                    y_offset = (printer_height - draw_height) // 2

                    hbmp = win32gui.LoadImage(0, temp_bmp, 0, 0, 0, 16)
                    if not hbmp:
                        raise RuntimeError(f"加载位图失败: 第{page_index + 1}页")

                    mem_dc = hdc.CreateCompatibleDC()
                    old_bmp = mem_dc.SelectObject(win32ui.CreateBitmapFromHandle(hbmp))
                    hdc.StretchBlt((x_offset, y_offset), (draw_width, draw_height), mem_dc, (0, 0), (img_width, img_height), win32con.SRCCOPY)
                    hdc.EndPage()
                finally:
                    if mem_dc and old_bmp:
                        mem_dc.SelectObject(old_bmp)
                    if mem_dc:
                        mem_dc.DeleteDC()
                    if hbmp:
                        win32gui.DeleteObject(hbmp)
                    try:
                        os.unlink(temp_bmp)
                    except Exception:
                        pass

            hdc.EndDoc()
            hdc.DeleteDC()
            hdc = None

            if document:
                document.close()
                document = None

            if printer_handle:
                win32print.ClosePrinter(printer_handle)
                printer_handle = None

            return {
                "success": True,
                "job_id": job_id,
                "printer_name": printer_name,
                "file_path": file_path,
                "message": "位图引擎打印任务已提交"
            }
        except Exception as e:
            try:
                if hdc:
                    hdc.AbortDoc()
            except Exception:
                pass
            return {"success": False, "message": f"位图引擎打印失败: {str(e)}"}
        finally:
            if document:
                try:
                    document.close()
                except Exception:
                    pass
            if hdc:
                try:
                    hdc.DeleteDC()
                except Exception:
                    pass
            if printer_handle:
                try:
                    win32print.ClosePrinter(printer_handle)
                except Exception:
                    pass
    
    def _print_raw_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """使用RAW方式打印文件"""
        printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
        
        # 创建打印作业
        job_info = (
            job_name or os.path.basename(file_path),  # pDocName
            None,  # pOutputFile
            'RAW'  # pDatatype
        )
        
        job_id = win32print.StartDocPrinter(printer_handle, 1, job_info)
        win32print.StartPagePrinter(printer_handle)
        
        # 读取文件内容并发送到打印机
        with open(file_path, 'rb') as f:
            file_data = f.read()
            win32print.WritePrinter(printer_handle, file_data)
        
        win32print.EndPagePrinter(printer_handle)
        win32print.EndDocPrinter(printer_handle)
        win32print.ClosePrinter(printer_handle)
        
        return {
            "success": True, 
            "job_id": job_id,
            "printer_name": printer_name,
            "file_path": file_path,
            "message": "打印任务已提交"
        }
    
    def _print_image_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """使用 win32print 方式打印图片文件"""
        printer_handle = None
        job_id = None
        layout_options = self._resolve_image_layout_options(print_options, file_path)
        try:
            from PIL import Image
            import tempfile
            import subprocess
            import os
            from portable_temp import get_temp_file_path
            
            # 打开图片并转换为适合打印的格式
            img = Image.open(file_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 创建临时BMP文件（使用 portable temp 目录）
            temp_bmp = get_temp_file_path(prefix="print_img", suffix=".bmp")
            img.save(temp_bmp, 'BMP')
            
            try:
                # 打开打印机（用于获取DEVMODE配置）
                printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
                
                # 使用win32ui进行实际的图片绘制和打印
                import win32ui
                import win32con
                import win32gui
                
                # 处理打印选项
                devmode = None
                if print_options:
                    try:
                        # 获取默认DEVMODE
                        devmode = win32print.GetPrinter(printer_handle, 2)['pDevMode']
                        if not devmode:
                            # 如果没有默认DEVMODE，创建一个新的
                            devmode = pywintypes.DEVMODEType()
                            devmode.DeviceName = printer_name
                        
                        # 处理纸张尺寸设置（优先使用文件自身尺寸）
                        paper_size = layout_options.get("paper_size")
                        # 如果是图像文件，尝试检测图像尺寸
                        if file_path and os.path.exists(file_path):
                            ext = os.path.splitext(file_path)[1].lower()
                            if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']:
                                try:
                                    from PIL import Image
                                    with Image.open(file_path) as img:
                                        img_width_inch = img.width / 96.0  # 假设图像 DPI 为 96
                                        img_height_inch = img.height / 96.0
                                        detected_size = self._identify_paper_size(img_width_inch, img_height_inch)
                                        if detected_size:
                                            logger.debug("Auto-detected image paper size: %s", detected_size)
                                            paper_size = detected_size
                                except Exception as e:
                                    logger.debug("Image size detection failed", exc_info=True)
                        
                        if paper_size and paper_size != '默认':
                            paper_size_map = {
                                '4X6': 58,
                                '6X4': 58,
                                'A4': win32con.DMPAPER_A4,
                                'LETTER': win32con.DMPAPER_LETTER,
                                'LEGAL': win32con.DMPAPER_LEGAL,
                                'A3': win32con.DMPAPER_A3,
                                'A5': win32con.DMPAPER_A5
                            }
                            paper_key = self._normalize_paper_size_for_win32(paper_size)
                            if paper_key:
                                paper_key = paper_key.upper()
                            else:
                                paper_key = str(paper_size).strip().upper()
                            if paper_key in paper_size_map:
                                devmode.PaperSize = paper_size_map[paper_key]
                                devmode.Fields |= win32con.DM_PAPERSIZE
                                if paper_key == '6X4':
                                    devmode.Orientation = win32con.DMORIENT_LANDSCAPE
                                    devmode.Fields |= win32con.DM_ORIENTATION
                                elif paper_key == '4X6':
                                    devmode.Orientation = win32con.DMORIENT_PORTRAIT
                                    devmode.Fields |= win32con.DM_ORIENTATION
                        
                        # 处理其他打印选项
                        if 'duplex' in print_options and print_options['duplex'] != '默认':
                            duplex_map = {
                                'None': win32con.DMDUP_SIMPLEX,
                                'DuplexNoTumble': win32con.DMDUP_VERTICAL,
                                'DuplexTumble': win32con.DMDUP_HORIZONTAL
                            }
                            if print_options['duplex'] in duplex_map:
                                devmode.Duplex = duplex_map[print_options['duplex']]
                                devmode.Fields |= win32con.DM_DUPLEX

                        if 'orientation' in print_options and print_options['orientation'] != '默认':
                            orientation_value = str(print_options['orientation']).lower()
                            if "landscape" in orientation_value or "横" in orientation_value:
                                devmode.Orientation = win32con.DMORIENT_LANDSCAPE
                            else:
                                devmode.Orientation = win32con.DMORIENT_PORTRAIT
                            devmode.Fields |= win32con.DM_ORIENTATION
                        
                        # 处理色彩模式（兼容 color_mode 和 color_model）
                        color_value = print_options.get('color_mode') or print_options.get('color_model')
                        if color_value and color_value != '默认':
                            color_str = str(color_value)
                            if color_str in ['Gray', 'Grayscale', 'grayscale', 'mono', 'monochrome']:
                                devmode.Color = win32con.DMCOLOR_MONOCHROME
                            else:
                                devmode.Color = win32con.DMCOLOR_COLOR
                            devmode.Fields |= win32con.DM_COLOR
                        
                        # 处理份数参数
                        copies = print_options.get('copies')
                        if copies:
                            try:
                                copies_int = int(copies)
                                if copies_int > 0:
                                    devmode.Copies = copies_int
                                    devmode.Fields |= win32con.DM_COPIES
                            except (ValueError, TypeError):
                                pass
                            
                    except Exception as e:
                        logger.debug("Applying image print options failed", exc_info=True)
                        devmode = None
                
                # 创建打印机设备上下文
                if devmode:
                    # 使用devmode创建设备上下文
                    hDC = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
                    hdc = win32ui.CreateDCFromHandle(hDC)
                else:
                    # 使用默认设置创建设备上下文
                    hdc = win32ui.CreateDC()
                    hdc.CreatePrinterDC(printer_name)
                
                job_id = hdc.StartDoc(job_name or os.path.basename(file_path))
                hdc.StartPage()
                
                # 获取打印机分辨率
                printer_width = hdc.GetDeviceCaps(win32con.HORZRES)
                printer_height = hdc.GetDeviceCaps(win32con.VERTRES)
                
                # 计算图片缩放：小图不放大，大图等比缩小到可打印区域
                img_width, img_height = img.size
                if img_width <= 0 or img_height <= 0:
                    raise ValueError(f"无效图片尺寸: {img_width}x{img_height}")

                new_width, new_height, scale = self._calculate_scaled_size(
                    img_width,
                    img_height,
                    printer_width,
                    printer_height,
                    layout_options.get("scale_mode", "fit"),
                    self._safe_float(layout_options.get("max_upscale"), 3.0)
                )
                
                # 检查是否居中打印（默认居中）
                center_print = True
                if print_options and 'center' in print_options:
                    center_value = str(print_options['center']).lower()
                    if center_value in ['false', 'no', '0', 'off']:
                        center_print = False
                
                # 计算打印位置（居中或左上角）
                if center_print:
                    x_offset = (printer_width - new_width) // 2
                    y_offset = (printer_height - new_height) // 2
                else:
                    x_offset = 0
                    y_offset = 0
                
                scale_mode = layout_options.get("scale_mode", "fit")
                max_upscale = self._safe_float(layout_options.get("max_upscale"), 3.0)
                if scale_mode == "actual":
                    logger.debug(
                        "Image print scaling: mode=actual src=%sx%s dst=%sx%s",
                        img_width,
                        img_height,
                        new_width,
                        new_height,
                    )
                elif scale_mode == "fill":
                    logger.debug(
                        "Image print scaling: mode=fill max_upscale=%s src=%sx%s dst=%sx%s",
                        max_upscale,
                        img_width,
                        img_height,
                        new_width,
                        new_height,
                    )
                elif scale < 1.0:
                    logger.debug(
                        "Image print scaling: mode=fit-shrink src=%sx%s dst=%sx%s",
                        img_width,
                        img_height,
                        new_width,
                        new_height,
                    )
                else:
                    logger.debug(
                        "Image print scaling: mode=fit max_upscale=%s src=%sx%s dst=%sx%s",
                        max_upscale,
                        img_width,
                        img_height,
                        new_width,
                        new_height,
                    )
                
                # 加载BMP文件为位图并绘制
                hbmp = win32gui.LoadImage(
                    0,  # hinst
                    temp_bmp,  # 文件路径
                    0,  # IMAGE_BITMAP
                    0, 0,  # 宽度和高度（0表示使用原始尺寸）
                    16  # LR_LOADFROMFILE
                )
                
                if hbmp:
                    # 创建内存DC
                    mem_dc = hdc.CreateCompatibleDC()
                    old_bmp = mem_dc.SelectObject(win32ui.CreateBitmapFromHandle(hbmp))
                    
                    # 使用StretchBlt绘制图片（支持居中）
                    hdc.StretchBlt(
                        (x_offset, y_offset),  # 目标位置（居中或左上角）
                        (new_width, new_height),  # 目标尺寸
                        mem_dc,  # 源DC
                        (0, 0),  # 源位置
                        (img_width, img_height),  # 源尺寸
                        win32con.SRCCOPY  # 复制模式
                    )
                    
                    # 清理资源
                    mem_dc.SelectObject(old_bmp)
                    mem_dc.DeleteDC()
                    win32gui.DeleteObject(hbmp)
                else:
                    # 如果位图加载失败，输出错误信息
                    hdc.TextOut(100, 100, f"Failed to load image: {os.path.basename(file_path)}")
                
                # 结束打印
                hdc.EndPage()
                hdc.EndDoc()
                hdc.DeleteDC()
                
                # 关闭打印机句柄
                if printer_handle:
                    win32print.ClosePrinter(printer_handle)
                    printer_handle = None
                
                if job_id:
                    logger.info("Image print submitted with job_id=%s", job_id)
                else:
                    logger.warning("Image print submitted but no job_id was returned")
                
            except Exception as print_error:
                logger.exception("Image print process failed")
                if printer_handle:
                    try:
                        win32print.ClosePrinter(printer_handle)
                    except:
                        pass
                raise print_error
            
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_bmp)
                except:
                    pass
            
            return {
                "success": True, 
                "job_id": job_id,
                "printer_name": printer_name,
                "file_path": file_path,
                "message": "图片打印任务已提交"
            }
            
        except Exception as e:
            logger.exception("Image printing failed")
            return {"success": False, "message": f"图片打印失败: {e}"}
    
    def get_printer_capabilities(self, printer_name: str, parser_manager=None) -> Dict:
        """获取打印机能力"""
        if not self.available:
            return {}
        
        try:
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            printer_info = win32print.GetPrinter(printer_handle, 2)
            port_name = printer_info.get('pPortName', '')
            
            # 获取设备上下文来获取当前状态信息
            try:
                import win32ui
                hdc = win32ui.CreateDC()
                hdc.CreatePrinterDC(printer_name)
                
                # 获取当前打印机分辨率
                current_dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
                current_dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY)
                
                # 获取纸张尺寸（以像素为单位）
                paper_width_pixels = hdc.GetDeviceCaps(win32con.HORZRES)
                paper_height_pixels = hdc.GetDeviceCaps(win32con.VERTRES)
                
                # 获取物理纸张尺寸（以0.1mm为单位）
                paper_width_mm = hdc.GetDeviceCaps(win32con.HORZSIZE)
                paper_height_mm = hdc.GetDeviceCaps(win32con.VERTSIZE)
                
                # 计算纸张尺寸（英寸）
                paper_width_inch = paper_width_mm / 25.4
                paper_height_inch = paper_height_mm / 25.4
                
                # 判断当前纸张类型
                current_paper_size = self._identify_paper_size(paper_width_inch, paper_height_inch)
                
                hdc.DeleteDC()
                
                # 使用DeviceCapabilities动态获取打印机支持的能力
                capabilities = {
                    "driver": printer_info.get('pDriverName', ''),
                    "port": port_name,
                    "location": printer_info.get('pLocation', ''),
                    "comment": printer_info.get('pComment', ''),
                    "current_paper_size": current_paper_size,
                    "paper_width_mm": paper_width_mm,
                    "paper_height_mm": paper_height_mm,
                    "paper_width_inch": round(paper_width_inch, 2),
                    "paper_height_inch": round(paper_height_inch, 2),
                    "printable_area_pixels": f"{paper_width_pixels}x{paper_height_pixels}"
                }
                
                # 动态获取支持的分辨率
                try:
                    resolutions = win32print.DeviceCapabilities(printer_name, port_name, win32con.DC_ENUMRESOLUTIONS)
                    if resolutions:
                        resolution_list = [f"{current_dpi_x}x{current_dpi_y} dpi"]  # 当前分辨率放在第一位
                        # DC_ENUMRESOLUTIONS返回的是字典列表，每个字典包含'x'和'y'键
                        for i in range(0, len(resolutions), 2):
                            if i + 1 < len(resolutions):
                                x_res = resolutions[i]
                                y_res = resolutions[i + 1]
                                res_str = f"{x_res}x{y_res} dpi"
                                if res_str not in resolution_list:
                                    resolution_list.append(res_str)
                        capabilities["resolution"] = resolution_list
                    else:
                        capabilities["resolution"] = [f"{current_dpi_x}x{current_dpi_y} dpi", "300dpi", "600dpi", "1200dpi"]
                except Exception as e:
                    print(f"获取分辨率失败: {e}")
                    capabilities["resolution"] = [f"{current_dpi_x}x{current_dpi_y} dpi", "300dpi", "600dpi", "1200dpi"]
                
                # 动态获取支持的纸张尺寸
                try:
                    paper_names = win32print.DeviceCapabilities(printer_name, port_name, win32con.DC_PAPERNAMES)
                    if paper_names:
                        page_size_list = [current_paper_size]  # 当前纸张放在第一位
                        for paper_name in paper_names:
                            if paper_name and paper_name not in page_size_list:
                                page_size_list.append(paper_name)
                        capabilities["page_size"] = page_size_list
                    else:
                        capabilities["page_size"] = [current_paper_size, "A4", "Letter", "Legal"]
                except Exception as e:
                    print(f"获取纸张尺寸失败: {e}")
                    capabilities["page_size"] = [current_paper_size, "A4", "Letter", "Legal"]
                
                # 动态获取双面打印支持
                try:
                    duplex_support = win32print.DeviceCapabilities(printer_name, port_name, win32con.DC_DUPLEX)
                    if duplex_support:
                        capabilities["duplex"] = ["None", "DuplexNoTumble", "DuplexTumble"]
                    else:
                        capabilities["duplex"] = ["None"]
                except Exception as e:
                    print(f"获取双面打印支持失败: {e}")
                    capabilities["duplex"] = ["None"]
                
                # 动态获取颜色支持
                try:
                    color_support = win32print.DeviceCapabilities(printer_name, port_name, win32con.DC_COLORDEVICE)
                    if color_support:
                        capabilities["color_model"] = ["RGB", "Gray"]
                    else:
                        capabilities["color_model"] = ["Gray"]
                except Exception as e:
                    print(f"获取颜色支持失败: {e}")
                    capabilities["color_model"] = ["RGB", "Gray"]
                
                # 动态获取介质类型
                try:
                    media_names = win32print.DeviceCapabilities(printer_name, port_name, win32con.DC_MEDIATYPENAMES)
                    if media_names:
                        capabilities["media_type"] = media_names
                    else:
                        capabilities["media_type"] = ["Plain", "Photo", "Transparency"]
                except Exception as e:
                    print(f"获取介质类型失败: {e}")
                    capabilities["media_type"] = ["Plain", "Photo", "Transparency"]
                
            except Exception as dc_error:
                print(f"获取设备上下文信息失败: {dc_error}")
                capabilities = {
                    "driver": printer_info.get('pDriverName', ''),
                    "port": port_name,
                    "location": printer_info.get('pLocation', ''),
                    "comment": printer_info.get('pComment', ''),
                    "resolution": ["300dpi", "600dpi", "1200dpi"],
                    "page_size": ["A4", "Letter", "Legal"],
                    "duplex": ["None"],
                    "color_model": ["RGB", "Gray"],
                    "media_type": ["Plain", "Photo", "Transparency"]
                }
            
            win32print.ClosePrinter(printer_handle)
            return capabilities
            
        except Exception as e:
            print(f"获取打印机能力失败: {e}")
            return {}
    
    def _get_printer_status_text(self, status: int) -> str:
        """获取打印机状态文本"""
        if status == 0:
            return "就绪"
        
        status_map = {
            0x00000001: "暂停",
            0x00000002: "错误",
            0x00000003: "正在删除",
            0x00000004: "缺纸",
            0x00000005: "缺纸",
            0x00000006: "手动送纸",
            0x00000007: "纸张问题",
            0x00000008: "离线",
            0x00000200: "输出满",
            0x00000400: "页面错误",
            0x00000800: "用户干预",
            0x00001000: "内存不足",
            0x00002000: "门开",
            0x00004000: "服务器未知",
            0x00008000: "省电模式"
        }
        
        for flag, text in status_map.items():
            if status & flag:
                return text
        return "未知状态"

    def _get_wmi_printer_status(self, printer_name: str):
        detail = self._get_wmi_printer_status_detail(printer_name)
        if detail:
            return detail.get("status_text")
        return None

    def _query_all_printers_wmi_batch(self) -> Dict[str, Optional[Dict[str, Any]]]:
        """一次性查询所有打印机的 WMI 状态，避免逐打印机重复启动 PowerShell。

        返回 {printer_name: status_detail_dict_or_None} 的字典。
        单次 PowerShell 调用即可获取全部打印机数据，降低管理页加载延迟。
        """
        import subprocess
        import json as _json
        try:
            powershell_cmd = (
                'Get-CimInstance Win32_Printer '
                '| Select-Object Name, WorkOffline, PrinterStatus, '
                'ExtendedPrinterStatus, DetectedErrorState, Availability '
                '| ConvertTo-Json'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", powershell_cmd],
                capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=15
            )
            if result.returncode != 0:
                logger.warning(
                    "WMI batch query failed: returncode=%s stderr=%s",
                    result.returncode,
                    result.stderr.strip() or "(none)",
                )
                return {}

            raw = result.stdout.strip()
            if not raw:
                return {}

            items = _json.loads(raw)
            # 如果是单个对象则包装为列表
            if isinstance(items, dict):
                items = [items]

            cache: Dict[str, Optional[Dict[str, Any]]] = {}
            for item in items:
                name = (item.get('Name') or '').strip()
                if not name:
                    continue
                work_offline = str(item.get('WorkOffline', ''))
                printer_status = str(item.get('PrinterStatus', ''))
                extended_status = str(item.get('ExtendedPrinterStatus', ''))
                detected_error_state = str(item.get('DetectedErrorState', ''))
                availability = str(item.get('Availability', ''))

                DETECTED_ERROR_STATE_MAP = {
                    "3": "缺纸", "4": "缺纸",
                    "5": "缺墨", "6": "缺墨",
                    "7": "门开", "8": "卡纸",
                    "9": "离线", "10": "需要维护",
                    "11": "输出满",
                }
                status_text = None
                if work_offline.lower() in ("true", "1", "yes"):
                    status_text = "离线"
                elif printer_status == "7" or extended_status == "7" or availability == "8":
                    status_text = "离线"
                elif printer_status == "4" or extended_status == "4":
                    status_text = "正在打印"
                elif printer_status in ("3", "5") or extended_status in ("3", "5"):
                    status_text = "就绪"
                elif detected_error_state and detected_error_state not in ("0", "1", "2"):
                    status_text = DETECTED_ERROR_STATE_MAP.get(
                        detected_error_state, "错误"
                    )

                cache[name] = {
                    "status_text": status_text,
                    "work_offline": work_offline,
                    "printer_status": printer_status,
                    "extended_status": extended_status,
                    "detected_error_state": detected_error_state,
                    "availability": availability,
                }
            logger.debug("WMI batch query returned %d printers", len(cache))
            return cache
        except Exception as e:
            logger.warning("WMI batch query exception: %s", e)
            return {}

    def _get_wmi_printer_status_detail(self, printer_name: str) -> Optional[Dict[str, Any]]:
        """通过PowerShell Get-CimInstance查询打印机扩展状态。

        替代已弃用的 wmic（Windows 11 24H2+ 已移除 wmic）。
        Get-CimInstance 在 PowerShell 3.0+ / 所有受支持 Windows 版本上均可用。

        优先使用批量查询缓存（30s TTL），避免逐打印机重复启动 PowerShell。
        缓存未命中时回退到单打印机查询。
        """
        import subprocess
        import time
        try:
            # 1. 先尝试从批量缓存获取（避免重复启动 PowerShell）
            now = time.time()
            if now - self._wmi_batch_cache_time > self._wmi_batch_cache_ttl:
                self._wmi_batch_cache = self._query_all_printers_wmi_batch()
                self._wmi_batch_cache_time = now

            # 缓存命中（包括值为 None 的条目，表示 WMI 中无此打印机）
            if printer_name in self._wmi_batch_cache:
                cached = self._wmi_batch_cache[printer_name]
                if self._wmi_query_state.get(printer_name) != "ok":
                    logger.debug("WMI printer status from batch cache: printer=%s", printer_name)
                    self._wmi_query_state[printer_name] = "ok"
                return cached

            # 2. 缓存未命中，回退到单打印机查询（处理边缘情况）
            safe_name = printer_name.replace("'", "''")
            wql = f"SELECT * FROM Win32_Printer WHERE Name='{safe_name}'"
            powershell_cmd = (
                f'Get-CimInstance -Query "{wql}" '
                '| Select-Object WorkOffline, PrinterStatus, ExtendedPrinterStatus, '
                'DetectedErrorState, Availability '
                '| Format-List'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", powershell_cmd],
                capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10
            )
            if result.returncode != 0:
                if self._wmi_query_state.get(printer_name) != "failed":
                    logger.warning(
                        "WMI printer status query failed: printer=%s returncode=%s stderr=%s",
                        printer_name,
                        result.returncode,
                        result.stderr.strip() or "(none)",
                    )
                    self._wmi_query_state[printer_name] = "failed"
                return None

            work_offline = None
            printer_status = None
            extended_status = None
            detected_error_state = None
            availability = None
            # Format-List 输出为 "Key : Value"（冒号+空格分隔），与旧 wmic 的 "Key=Value" 不同
            for line in result.stdout.splitlines():
                if line.startswith("WorkOffline"):
                    work_offline = line.split(":", 1)[1].strip()
                elif line.startswith("PrinterStatus"):
                    printer_status = line.split(":", 1)[1].strip()
                elif line.startswith("ExtendedPrinterStatus"):
                    extended_status = line.split(":", 1)[1].strip()
                elif line.startswith("DetectedErrorState"):
                    detected_error_state = line.split(":", 1)[1].strip()
                elif line.startswith("Availability"):
                    availability = line.split(":", 1)[1].strip()

            # WMI DetectedErrorState → 中文状态映射
            # ref: https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-printer
            DETECTED_ERROR_STATE_MAP = {
                "3": "缺纸",      # Low Paper
                "4": "缺纸",      # No Paper
                "5": "缺墨",      # Low Toner
                "6": "缺墨",      # No Toner
                "7": "门开",      # Door Open
                "8": "卡纸",      # Jammed
                "9": "离线",      # Offline
                "10": "需要维护",  # Service Requested
                "11": "输出满",    # Output Bin Full
            }

            status_text = None
            if work_offline and work_offline.lower() in ("true", "1", "yes"):
                status_text = "离线"
            elif printer_status == "7" or extended_status == "7" or availability == "8":
                status_text = "离线"
            elif printer_status == "4" or extended_status == "4":
                status_text = "正在打印"
            elif printer_status in ("3", "5") or extended_status in ("3", "5"):
                status_text = "就绪"
            elif detected_error_state and detected_error_state not in ("0", "1", "2"):
                status_text = DETECTED_ERROR_STATE_MAP.get(
                    detected_error_state, "错误"
                )

            if self._wmi_query_state.get(printer_name) != "ok":
                logger.debug("WMI printer status query available: printer=%s", printer_name)
                self._wmi_query_state[printer_name] = "ok"

            # 将单打印机查询结果回填到批量缓存中
            result_item = {
                "status_text": status_text,
                "work_offline": work_offline,
                "printer_status": printer_status,
                "extended_status": extended_status,
                "detected_error_state": detected_error_state,
                "availability": availability,
            }
            self._wmi_batch_cache[printer_name] = result_item
            return result_item
        except FileNotFoundError:
            # PowerShell 不可用（极端罕见的 Windows 环境）
            if self._wmi_query_state.get(printer_name) != "failed":
                logger.warning("PowerShell not available for WMI printer status query: printer=%s", printer_name)
                self._wmi_query_state[printer_name] = "failed"
            return None
        except Exception as e:
            if self._wmi_query_state.get(printer_name) != "failed":
                logger.warning("WMI printer status query exception: printer=%s error=%s", printer_name, e)
                self._wmi_query_state[printer_name] = "failed"
            return None

    def _enrich_status_from_printer_info_3(
        self, printer_name: str, result_dict: Dict[str, Any]
    ) -> None:
        """当 Win32 Status bitmask=0 且 WMI 不可用时，从 PRINTER_INFO_3 获取
        spooler 维护的独立状态字符串作为兜底。

        对于网络打印机，spooler 可能持有 "打印机脱机"、"无法与打印机通讯"
        等更准确的状态描述，即使 Status bitmask 显示为 0（就绪）。
        """
        try:
            printer_handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
            printer_info_3 = win32print.GetPrinter(printer_handle, 3)
            win32print.ClosePrinter(printer_handle)

            spooler_status = printer_info_3.get('Status', '')
            if spooler_status and spooler_status.strip():
                result_dict["status_text"] = spooler_status.strip()
        except Exception:
            pass  # 兜底查询失败则保持原有的 status_text

    def _normalize_paper_size_for_win32(self, paper_size: Optional[str]) -> Optional[str]:
        """将 'Letter (横向)' 等规范化为 win32 可识别的名称"""
        s = str(paper_size or "").strip()
        if not s:
            return None
        if " (横向)" in s or " (landscape)" in s.lower():
            s = s.split(" (")[0].strip()
        return s if s else None

    def _identify_paper_size(self, width_inch: float, height_inch: float) -> str:
        """根据尺寸识别纸张类型"""
        # 常见纸张尺寸（英寸）
        paper_sizes = {
            "4x6": (4.0, 6.0),
            "5x7": (5.0, 7.0),
            "6x8": (6.0, 8.0),
            "8x10": (8.0, 10.0),
            "A4": (8.27, 11.69),
            "Letter": (8.5, 11.0),
            "Legal": (8.5, 14.0),
            "A3": (11.69, 16.54),
            "Tabloid": (11.0, 17.0)
        }
        
        # 允许的误差范围（英寸）
        tolerance = 0.2
        
        for size_name, (std_width, std_height) in paper_sizes.items():
            # 检查正向匹配
            if (abs(width_inch - std_width) <= tolerance and 
                abs(height_inch - std_height) <= tolerance):
                return size_name
            # 检查旋转匹配（横向）
            if (abs(width_inch - std_height) <= tolerance and 
                abs(height_inch - std_width) <= tolerance):
                return f"{size_name} (横向)"
        
        # 如果没有匹配的标准尺寸，返回实际尺寸
        return f"{width_inch:.1f}x{height_inch:.1f}英寸"


class WindowsPrintJobMonitor:
    """Windows 打印任务 WMI 事件监听器
    
    使用 WMI 事件通知机制实时监控打印任务状态变化，
    相比轮询方式具有更低延迟和更准确的状态判断。
    """
    
    def __init__(self):
        self.available = WMI_AVAILABLE and WIN32_AVAILABLE
        self.monitors = {}  # {monitor_key: monitor_thread}
        self.running = False
        
        if not self.available:
            print(" [WARNING] WMI 打印任务监听器不可用")
    
    def start_job_monitor(self, printer_name: str, job_id: int, 
                         on_status_change: Optional[Callable[[Dict[str, Any]], None]] = None,
                         on_complete: Optional[Callable[[Dict[str, Any]], None]] = None):
        """启动打印任务事件监听
        
        Args:
            printer_name: 打印机名称
            job_id: 打印任务ID
            on_status_change: 状态变化回调函数（可选）
            on_complete: 任务完成回调函数（必须）
        
        Returns:
            监听器键值（用于停止监听）
        """
        if not self.available:
            print(" [WARNING] WMI不可用，无法启动事件监听")
            return None
        
        if not on_complete:
            print(" [WARNING] 必须提供 on_complete 回调函数")
            return None
        
        import threading
        
        monitor_key = f"{printer_name}:{job_id}"
        
        def monitor_thread():
            """WMI 事件监听线程"""
            try:
                # COM 初始化（每个线程必须独立初始化）
                pythoncom.CoInitialize()
                
                print(f" [INFO] 启动 WMI 事件监听: {monitor_key}")
                
                # 连接 WMI
                c = wmi.WMI()
                
                # 构造 WQL 查询：监听特定打印任务的删除事件
                # Win32_PrintJob 的 Name 格式为 "printer_name:job_id"
                wql_delete = f"""
                    SELECT * FROM __InstanceDeletionEvent WITHIN 2
                    WHERE TargetInstance ISA 'Win32_PrintJob'
                    AND TargetInstance.Name = '{monitor_key}'
                """
                
                # 如果需要监听状态变化（可选）
                if on_status_change:
                    wql_modify = f"""
                        SELECT * FROM __InstanceModificationEvent WITHIN 2
                        WHERE TargetInstance ISA 'Win32_PrintJob'
                        AND TargetInstance.Name = '{monitor_key}'
                    """
                    
                    # 创建修改事件监听器（非阻塞）
                    modify_watcher = c.watch_for(
                        raw_wql=wql_modify,
                        notification_type="Modification",
                        wmi_class="Win32_PrintJob"
                    )
                
                # 创建删除事件监听器（阻塞等待）
                delete_watcher = c.watch_for(
                    raw_wql=wql_delete,
                    notification_type="Deletion",
                    wmi_class="Win32_PrintJob"
                )
                
                print(f" [INFO] WMI 监听器已就绪: {monitor_key}")
                
                # 阻塞等待删除事件（任务完成/取消/失败都会触发删除）
                deleted_event = delete_watcher()
                
                # 提取任务信息
                target_instance = deleted_event.TargetInstance
                
                job_info = {
                    "job_id": job_id,
                    "printer_name": printer_name,
                    "document": getattr(target_instance, 'Document', 'Unknown'),
                    "status": "completed",  # WMI 删除事件无法区分成功/失败，默认为完成
                    "pages_printed": getattr(target_instance, 'PagesPrinted', 0),
                    "total_pages": getattr(target_instance, 'TotalPages', 0),
                    "time_submitted": getattr(target_instance, 'TimeSubmitted', None)
                }
                
                print(f" [INFO] WMI 检测到任务完成: {monitor_key}")
                print(f"   └─ 文档: {job_info['document']}")
                print(f"   └─ 页数: {job_info['pages_printed']}/{job_info['total_pages']}")
                
                # 调用完成回调
                if on_complete:
                    on_complete(job_info)
                
            except Exception as e:
                print(f" [ERROR] WMI 监听异常: {monitor_key} - {e}")
                # 异常时也调用回调，避免任务卡住
                if on_complete:
                    on_complete({
                        "job_id": job_id,
                        "printer_name": printer_name,
                        "status": "error",
                        "error": str(e)
                    })
            finally:
                # COM 清理
                pythoncom.CoUninitialize()
                # 移除监听器记录
                if monitor_key in self.monitors:
                    del self.monitors[monitor_key]
                print(f" [INFO] WMI 监听器已停止: {monitor_key}")
        
        # 启动监听线程
        thread = threading.Thread(target=monitor_thread, daemon=True, name=f"WMI-Monitor-{monitor_key}")
        thread.start()
        
        # 记录监听器
        self.monitors[monitor_key] = thread
        
        return monitor_key
    
    def stop_job_monitor(self, monitor_key: str):
        """停止指定的任务监听（注意：WMI 监听是阻塞的，只能等待其自然结束）"""
        if monitor_key in self.monitors:
            print(f"⏸ [INFO] 请求停止 WMI 监听: {monitor_key}")
            # WMI 的 watch_for 是阻塞的，无法主动中断
            # 只能等待事件触发或线程自然结束
            del self.monitors[monitor_key]
    
    def get_active_monitors(self) -> List[str]:
        """获取当前活跃的监听器列表"""
        return list(self.monitors.keys())
    
    def stop_all(self):
        """停止所有监听器"""
        print(f" [INFO] 停止所有 WMI 监听器（共 {len(self.monitors)} 个）")
        self.monitors.clear()

