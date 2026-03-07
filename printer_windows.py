"""
Windows打印机实现
包含所有Windows平台的打印机操作
"""

import platform
import os
import json
import shutil
from typing import List, Dict, Any, Callable, Optional

# Windows特定导入
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
        import win32con
        import pywintypes
        import pythoncom
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
    
    try:
        import wmi
        WMI_AVAILABLE = True
    except ImportError:
        WMI_AVAILABLE = False
        print(" [WARNING] WMI模块不可用，将使用轮询方式监控打印任务")
else:
    WIN32_AVAILABLE = False
    WMI_AVAILABLE = False


class WindowsEnterprisePrinter:
    """Windows企业级打印机操作类"""
    
    def __init__(self):
        self.available = WIN32_AVAILABLE
        if not self.available:
            print(" [WARNING] Windows打印API不可用，请安装pywin32")
    
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
                with open(config_path, "r", encoding="utf-8") as f:
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
                    printer_handle = win32print.OpenPrinter(printer_name)
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
            printer_handle = win32print.OpenPrinter(printer_name)
            printer_info = win32print.GetPrinter(printer_handle, 2)
            win32print.ClosePrinter(printer_handle)
            
            status = printer_info.get('Status', 0)
            attributes = printer_info.get('Attributes', 0)
            wmi_detail = self._get_wmi_printer_status_detail(printer_name)
            
            # 首先检查是否设置为离线工作
            if attributes & 0x00000004:  # PRINTER_ATTRIBUTE_WORK_OFFLINE
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
            printer_handle = win32print.OpenPrinter(printer_name)
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
            printer_handle = win32print.OpenPrinter(printer_name)
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
    
    def _get_latest_job_id(self, printer_name: str, job_name: str = None, max_wait: float = 2.0) -> Optional[int]:
        """从打印队列获取最新的job_id
        
        Args:
            printer_name: 打印机名称
            job_name: 任务名称（用于匹配）
            max_wait: 最大等待时间（秒），因为任务可能需要短暂时间才出现在队列中
        
        Returns:
            job_id或None
        """
        if not self.available:
            return None
        
        import time
        
        try:
            # 多次尝试，因为任务可能需要短暂时间才出现在队列中
            for attempt in range(int(max_wait * 10)):  # 每0.1秒检查一次
                try:
                    printer_handle = win32print.OpenPrinter(printer_name)
                    jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
                    win32print.ClosePrinter(printer_handle)
                    
                    if jobs:
                        # 如果提供了job_name，尝试匹配
                        if job_name:
                            for job in jobs:
                                doc_name = job.get("pDocument", "")
                                if doc_name and job_name in doc_name:
                                    return job["JobId"]
                        
                        # 如果没有匹配到或没有提供job_name，返回最新的（JobId最大的）
                        latest_job = max(jobs, key=lambda j: j.get("JobId", 0))
                        job_id = latest_job.get("JobId")
                        if job_id:
                            return job_id
                
                except Exception:
                    pass
                
                time.sleep(0.1)
            
            print(f" [WARNING] 在{max_wait}秒内未能从打印队列获取job_id")
            return None
            
        except Exception as e:
            print(f" [ERROR] 获取最新job_id失败: {e}")
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
            printer_config: 打印机配置信息（包含IP、端口、协议等）
        """
        if not self.available:
            return {"success": False, "message": "Windows打印API不可用"}
        
        try:
            # 优先检查打印机是否已安装在系统中
            is_system_printer = False
            try:
                # 尝试打开打印机句柄，检查是否为系统已安装的打印机
                printer_handle = win32print.OpenPrinter(printer_name)
                win32print.ClosePrinter(printer_handle)
                is_system_printer = True
                print(f" [INFO] 检测到系统已安装打印机: {printer_name}")
            except:
                is_system_printer = False
                print(f" [INFO] 打印机未在系统中安装: {printer_name}")
            
            # 如果打印机已安装在系统中，使用系统打印（支持参数传递）
            if is_system_printer:
                print(f" [INFO] 使用系统打印（支持打印参数）")
                # 继续使用系统打印方式，支持参数传递
            else:
                # 打印机未安装，检查是否可以使用 Socket 直连
                if printer_config:
                    protocol = printer_config.get("protocol", "")
                    ip = printer_config.get("ip")
                    port = printer_config.get("port")
                    
                    # HP JetDirect 或 RAW 协议（仅在打印机未安装时使用）
                    if protocol in ["hp_jetdirect", "raw", "socket"] and ip:
                        if not port:
                            port = 9100  # HP JetDirect 默认端口
                        
                        # 检查是否有打印参数需求
                        has_print_options = print_options and any(print_options.values())
                        if has_print_options:
                            print(f" [WARNING] Socket打印不支持参数传递（双面、彩色等），建议先在系统中安装打印机")
                            print(f"   当前参数将被忽略: {print_options}")
                        
                        print(f" [INFO] 使用Socket直连打印（无参数支持）: {ip}:{port}")
                        return self._print_via_socket(ip, port, file_path, job_name)
                
                # 既没有安装也没有配置Socket，返回错误
                return {"success": False, "message": f"打印机 {printer_name} 未安装且无法通过Socket连接"}
            
            # 检查文件类型（系统打印路径）
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']:
                # 图片文件使用GDI打印
                return self._print_image_file(printer_name, file_path, job_name, print_options)
            elif file_ext == '.pdf':
                # PDF文件尝试调用系统打印
                return self._print_pdf_file(printer_name, file_path, job_name, print_options)
            elif file_ext in ['.doc', '.docx']:
                # Word文档先转PDF再打印
                return self._print_word_file(printer_name, file_path, job_name, print_options)
            else:
                # 文本文件使用RAW打印
                return self._print_raw_file(printer_name, file_path, job_name, print_options)
                
        except Exception as e:
            print(f"提交打印任务失败: {e}")
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
            
            printer_handle = win32print.OpenPrinter(printer_name)
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
                
                # 设置纸张大小
                if 'paper_size' in print_options:
                    paper_size = print_options['paper_size']
                    paper_size_map = {
                        'A4': win32con.DMPAPER_A4,
                        'A3': win32con.DMPAPER_A3,
                        'A5': win32con.DMPAPER_A5,
                        'Letter': win32con.DMPAPER_LETTER,
                        'Legal': win32con.DMPAPER_LEGAL,
                    }
                    if paper_size in paper_size_map:
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
        import time
        import subprocess
        
        print(f"[INFO] 开始打印PDF: {file_path} -> {printer_name}")
        
        try:
            abs_path = os.path.abspath(file_path)
            filename_lower = os.path.basename(abs_path).lower()

            # 选择PDF打印引擎：sumatra / system / auto(默认)
            pdf_engine = "auto"
            if print_options and print_options.get("pdf_engine"):
                pdf_engine = str(print_options.get("pdf_engine", "auto")).strip().lower()
            elif self._get_setting("pdf_engine"):
                pdf_engine = str(self._get_setting("pdf_engine", "auto")).strip().lower()

            # auto策略：发票类PDF优先走系统printto（Edge/系统打印链路）
            looks_like_invoice = ("发票" in filename_lower) or ("invoice" in filename_lower)
            prefer_system_engine = (pdf_engine == "system") or (pdf_engine == "auto" and looks_like_invoice)
            
            # 使用自动发现逻辑
            sumatra_path = self._find_sumatra_pdf_path()
            
            if sumatra_path and not prefer_system_engine:
                try:
                    print(f"[INFO] 使用 SumatraPDF 打印: {sumatra_path}")
                    cmd = [sumatra_path, "-print-to", printer_name, "-silent", "-exit-when-done"]
                    
                    # 构建打印设置字符串
                    print_settings = []
                    
                    if print_options:
                        
                        # 处理双面打印参数
                        duplex_value = print_options.get("duplex")
                        if duplex_value in ["DuplexNoTumble", "LongEdge", "long", "long_edge"]:
                            print_settings.append("duplexlong")
                        elif duplex_value in ["DuplexTumble", "ShortEdge", "short", "short_edge"]:
                            print_settings.append("duplexshort")
                        elif duplex_value in ["None", "none", "simplex", "single"]:
                            print_settings.append("simplex")
                        
                        # 处理色彩模式参数（兼容 color_mode 和 color_model）
                        color_value = print_options.get("color_mode") or print_options.get("color_model")
                        if color_value:
                            color_str = str(color_value).lower()
                            if color_str in ["grayscale", "gray", "mono", "monochrome", "black"]:
                                print_settings.append("monochrome")
                            elif color_str in ["color", "colour", "rgb"]:
                                print_settings.append("color")
                        
                        # 处理纸张大小参数
                        paper_size = print_options.get("paper_size")
                        if paper_size:
                            paper_str = str(paper_size).upper()
                            # SumatraPDF 支持的纸张大小格式
                            if paper_str in ["A4", "A3", "A5", "LETTER", "LEGAL", "TABLOID"]:
                                print_settings.append(paper_str.lower())
                        
                        # 处理份数参数（SumatraPDF 使用 Nxcopies 格式）
                        copies = print_options.get("copies")
                        if copies:
                            try:
                                copies_int = int(copies)
                                if copies_int > 1:
                                    print_settings.append(f"{copies_int}x")
                            except (ValueError, TypeError):
                                pass
                    
                    # 将所有打印设置合并为一个逗号分隔的字符串
                    if print_settings:
                        cmd.extend(["-print-settings", ",".join(print_settings)])
                    
                    cmd.append(abs_path)
                    result = subprocess.run(
                        cmd,
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                    )
                    if result.returncode != 0:
                        return {"success": False, "message": f"SumatraPDF打印失败: {result.stderr.strip() or result.stdout.strip()}"}
                    print(f"[INFO] SumatraPDF 打印成功 (exitCode: {result.returncode})")
                    
                    # 尝试从打印队列获取job_id（SumatraPDF提交后立即查询）
                    job_id = self._get_latest_job_id(printer_name, job_name)
                    if job_id:
                        print(f"[INFO] 获取到打印任务ID: {job_id}")
                    else:
                        print(f"[WARN] 未能从打印队列获取job_id（任务可能已完成或虚拟打印机）")
                    
                    return {"success": True, "message": "SumatraPDF 打印任务已提交", "job_id": job_id}
                except Exception as e:
                    return {"success": False, "message": f"SumatraPDF打印失败: {str(e)}"}

            if prefer_system_engine:
                reason = "配置指定" if pdf_engine == "system" else "发票PDF自动避开Sumatra"
                print(f"[INFO] 使用系统打印引擎 (printto/print): {reason}")
            
            # 如果没有 SumatraPDF，使用 ShellExecute
            # 优先使用 printto 动词（不修改默认打印机）
            res = 33
            print(f"[INFO] 尝试使用 'printto' 动词打印: {abs_path}")
            res = win32api.ShellExecute(0, "printto", abs_path, f'"{printer_name}"', ".", 0)
            
            # 仅当 printto 失败且错误码为 31（无关联程序）时，才回退到修改默认打印机的方案
            if res <= 32:
                if res == 31:
                    print(f"[WARN] 'printto' 失败 (错误码 31: 无关联程序)，回退到修改默认打印机方案...")
                    default_printer = win32print.GetDefaultPrinter()
                    
                    try:
                        if default_printer != printer_name:
                            print(f"[INFO] 临时切换默认打印机: {default_printer} -> {printer_name}")
                            win32print.SetDefaultPrinter(printer_name)
                        
                        print(f"[INFO] 尝试使用 'print' 动词打印: {abs_path}")
                        res = win32api.ShellExecute(0, "print", abs_path, None, ".", 0)
                    finally:
                        if default_printer != printer_name:
                            print(f"[INFO] 恢复默认打印机: {default_printer}")
                            win32print.SetDefaultPrinter(default_printer)
                    
                    if res <= 32:
                        return {"success": False, "message": f"ShellExecute调用失败, 错误码: {res}"}
                else:
                    return {"success": False, "message": f"printto 调用失败, 错误码: {res}"}
            
            # 轮询获取打印任务ID
            job_id = None
            max_attempts = 5
            
            for attempt in range(max_attempts):
                try:
                    printer_handle = win32print.OpenPrinter(printer_name)
                    jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
                    win32print.ClosePrinter(printer_handle)
                    
                    if jobs:
                        latest_job = max(jobs, key=lambda x: x['JobId'])
                        job_id = latest_job['JobId']
                        print(f"[INFO] 获取到打印任务ID: {job_id} (第{attempt+1}次尝试)")
                        break
                    elif attempt < max_attempts - 1:
                        time.sleep(1)
                except Exception as e:
                    print(f"[WARN] 第{attempt+1}次获取打印任务ID失败: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(1)
            
            if not job_id:
                print(f"[WARN] {max_attempts}次尝试后仍未获取到job_id，虚拟打印机可能不经过后台程序")
            
            return {
                "success": True, 
                "job_id": job_id, 
                "printer_name": printer_name,
                "file_path": file_path,
                "message": "PDF打印命令已发送"
            }
            
        except Exception as e:
            print(f"[ERROR] PDF打印失败: {e}")
            return {"success": False, "message": f"PDF打印失败: {str(e)}"}
    
    def _print_raw_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """使用RAW方式打印文件"""
        printer_handle = win32print.OpenPrinter(printer_name)
        
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
        """使用win32print方式打印图片文件"""
        printer_handle = None
        job_id = None
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
                printer_handle = win32print.OpenPrinter(printer_name)
                
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
                        
                        # 处理纸张尺寸设置
                        if 'page_size' in print_options:
                            page_size = print_options['page_size']
                            if page_size and page_size != '默认':
                                # 设置纸张尺寸
                                paper_size_map = {
                                    '4x6': 58,  # DMPAPER_4X6
                                    '6x4': 58,  # 6x4实际上是4x6横向
                                    'A4': win32con.DMPAPER_A4,
                                    'Letter': win32con.DMPAPER_LETTER,
                                    'Legal': win32con.DMPAPER_LEGAL,
                                    'A3': win32con.DMPAPER_A3
                                }
                                
                                if page_size in paper_size_map:
                                    devmode.PaperSize = paper_size_map[page_size]
                                    devmode.Fields |= win32con.DM_PAPERSIZE
                                    
                                    # 如果是6x4，设置横向打印
                                    if page_size == '6x4':
                                        devmode.Orientation = win32con.DMORIENT_LANDSCAPE
                                        devmode.Fields |= win32con.DM_ORIENTATION
                                    else:
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
                        print(f"设置打印选项失败: {e}")
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
                
                # 开始打印文档（这里不会重新生成job_id，使用之前获取的）
                hdc.StartDoc(job_name or os.path.basename(file_path))
                hdc.StartPage()
                
                # 获取打印机分辨率
                printer_width = hdc.GetDeviceCaps(win32con.HORZRES)
                printer_height = hdc.GetDeviceCaps(win32con.VERTRES)
                
                # 计算图片缩放：小图不放大，大图等比缩小到可打印区域
                img_width, img_height = img.size
                if img_width <= 0 or img_height <= 0:
                    raise ValueError(f"无效图片尺寸: {img_width}x{img_height}")

                fit_scale = min(printer_width / img_width, printer_height / img_height)
                scale = min(1.0, fit_scale)
                new_width = max(1, int(img_width * scale))
                new_height = max(1, int(img_height * scale))
                
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
                
                if scale < 1.0:
                    print(f" [INFO] 图片打印采用等比缩小: {img_width}x{img_height} -> {new_width}x{new_height}")
                else:
                    print(f" [INFO] 图片打印保持原尺寸: {img_width}x{img_height}")
                
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
                
                # 打印完成后获取真实的job_id
                import time
                time.sleep(0.5)  # 等待任务进入队列
                job_id = self._get_latest_job_id(printer_name, job_name or os.path.basename(file_path))
                
                if job_id:
                    print(f" [INFO] 图片打印成功，获取到任务ID: {job_id}")
                else:
                    print(f" [WARNING] 图片打印成功但无法获取任务ID")
                
            except Exception as print_error:
                print(f"打印过程失败: {print_error}")
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
            print(f"图片打印失败: {e}")
            return {"success": False, "message": f"图片打印失败: {e}"}
    
    def get_printer_capabilities(self, printer_name: str, parser_manager=None) -> Dict:
        """获取打印机能力"""
        if not self.available:
            return {}
        
        try:
            printer_handle = win32print.OpenPrinter(printer_name)
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

    def _get_wmi_printer_status_detail(self, printer_name: str) -> Optional[Dict[str, Any]]:
        import subprocess
        try:
            safe_name = printer_name.replace("'", "''")
            result = subprocess.run(
                ["wmic", "printer", "where", f"Name='{safe_name}'", "get", "WorkOffline,PrinterStatus,ExtendedPrinterStatus,DetectedErrorState,Availability", "/format:list"],
                capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10
            )
            if result.returncode != 0:
                return None
            work_offline = None
            printer_status = None
            extended_status = None
            detected_error_state = None
            availability = None
            for line in result.stdout.splitlines():
                if line.startswith("WorkOffline="):
                    work_offline = line.split("=", 1)[1].strip()
                elif line.startswith("PrinterStatus="):
                    printer_status = line.split("=", 1)[1].strip()
                elif line.startswith("ExtendedPrinterStatus="):
                    extended_status = line.split("=", 1)[1].strip()
                elif line.startswith("DetectedErrorState="):
                    detected_error_state = line.split("=", 1)[1].strip()
                elif line.startswith("Availability="):
                    availability = line.split("=", 1)[1].strip()

            status_text = None
            if work_offline and work_offline.lower() in ("true", "1", "yes"):
                status_text = "离线"
            elif printer_status == "7" or extended_status == "7" or detected_error_state == "9" or availability == "8":
                status_text = "离线"
            elif printer_status == "4" or extended_status == "4":
                status_text = "正在打印"
            elif printer_status in ("3", "5") or extended_status in ("3", "5"):
                status_text = "就绪"
            elif detected_error_state and detected_error_state not in ("0", "2"):
                status_text = "错误"

            return {
                "status_text": status_text,
                "work_offline": work_offline,
                "printer_status": printer_status,
                "extended_status": extended_status,
                "detected_error_state": detected_error_state,
                "availability": availability,
            }
        except Exception:
            return None
    
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

