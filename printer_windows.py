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
        print("⚠️ [WARNING] WMI模块不可用，将使用轮询方式监控打印任务")
else:
    WIN32_AVAILABLE = False
    WMI_AVAILABLE = False


class WindowsEnterprisePrinter:
    """Windows企业级打印机操作类"""
    
    def __init__(self):
        self.available = WIN32_AVAILABLE
        if not self.available:
            print("⚠️ [WARNING] Windows打印API不可用，请安装pywin32")
    
    def discover_local_printers(self) -> List[Dict]:
        """发现本地已安装的打印机"""
        # 直接调用discover_printers方法，避免重复代码
        return self.discover_printers()
    
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
        if not self.available:
            return "Windows打印API不可用"
        
        try:
            printer_handle = win32print.OpenPrinter(printer_name)
            printer_info = win32print.GetPrinter(printer_handle, 2)
            win32print.ClosePrinter(printer_handle)
            
            status = printer_info['Status']
            attributes = printer_info['Attributes']
            
            # 首先检查是否设置为离线工作
            if attributes & 0x00000004:  # PRINTER_ATTRIBUTE_WORK_OFFLINE
                return "离线"
            
            # 然后根据状态值判断
            status_text = self._get_printer_status_text(status)
            wmi_status_text = self._get_wmi_printer_status(printer_name)
            if wmi_status_text:
                return wmi_status_text
            return status_text
                
        except Exception as e:
            return f"获取状态失败: {e}"
    
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
    
    def submit_print_job(self, printer_name: str, file_path: str, job_name: str = "", print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """提交打印任务，返回任务信息"""
        if not self.available:
            return {"success": False, "message": "Windows打印API不可用"}
        
        try:
            # 检查文件类型
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
        
        pdf_path = None
        try:
            # 初始化COM库（多线程环境下必需）
            pythoncom.CoInitialize()
            
            # 创建临时PDF文件路径
            temp_dir = tempfile.gettempdir()
            pdf_filename = f"{os.path.splitext(os.path.basename(file_path))[0]}.pdf"
            pdf_path = os.path.join(temp_dir, pdf_filename)
            
            # 如果临时PDF已存在，先删除
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except:
                    pass
            
            print(f"📄 [INFO] 正在将Word文档转换为PDF: {file_path} -> {pdf_path}")

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
                    print(f"✅ [INFO] 文档转PDF成功 (使用 {prog_id})")
                    return True
                except Exception as e:
                    print(f"⚠️ [WARNING] 文档转PDF失败 ({prog_id}): {e}")
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
                    return self._print_pdf_file(printer_name, pdf_path, job_name, print_options)

            soffice = self._find_libreoffice_path()
            if soffice:
                try:
                    result = subprocess.run(
                        [soffice, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, abs_file_path],
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                    )
                    if result.returncode == 0 and os.path.exists(pdf_path):
                        print("✅ [INFO] 文档转PDF成功 (使用 LibreOffice)")
                        return self._print_pdf_file(printer_name, pdf_path, job_name, print_options)
                except Exception as e:
                    print(f"⚠️ [WARNING] 文档转PDF失败 (LibreOffice): {e}")

            if convert_with_com("Word.Application"):
                return self._print_pdf_file(printer_name, pdf_path, job_name, print_options)

            return {"success": False, "message": "文档转PDF失败，未找到可用的文档处理程序"}
            
        except Exception as e:
            print(f"❌ [ERROR] 处理Word文档失败: {e}")
            return {"success": False, "message": f"Word文档处理失败: {str(e)}"}
        finally:
            # 清理COM库
            pythoncom.CoUninitialize()

    def _print_pdf_file(self, printer_name: str, file_path: str, job_name: str, print_options: Dict[str, str] = None) -> Dict[str, Any]:
        """打印PDF文件 (使用ShellExecute调用默认PDF阅读器打印)"""
        import win32api
        import win32print
        import time
        import subprocess
        
        try:
            print(f"🖨️ [INFO] 正在调用系统命令打印PDF: {file_path} -> {printer_name}")
            
            # 使用 ShellExecute 的 "printto" 动词
            # 参数: hwnd, operation, file, parameters, directory, showCmd
            # printto 参数通常是: "printer_name"
            # 注意：某些PDF阅读器可能不支持 printto，或者参数格式不同
            # 标准做法是: printto "filename" "printer_name" "driver_name" "port_name"
            # 但 win32api.ShellExecute 的参数 passing 比较特殊
            
            # 尝试方法1: 使用 printto
            # 这种方式依赖于系统默认PDF阅读器支持 printto 命令
            # 大多数阅读器(Acrobat, SumatraPDF)支持
            # Edge 浏览器可能不支持静默打印
            
            # 为了更稳健，我们可以尝试使用 Ghostscript (如果安装了) 或 SumatraPDF
            # 但这里我们先尝试系统默认机制
            
            # 获取默认打印机，以便恢复（虽然printto指定了打印机，但某些程序会更改默认打印机）
            default_printer = win32print.GetDefaultPrinter()
            
            abs_path = os.path.abspath(file_path)

            sumatra_path = self._resolve_path(self._get_setting("pdf_printer_path"))
            if sumatra_path:
                try:
                    cmd = [sumatra_path, "-print-to", printer_name, "-silent", "-exit-when-done"]
                    duplex_setting = None
                    if print_options:
                        duplex_value = print_options.get("duplex")
                        if duplex_value in ["DuplexNoTumble", "LongEdge", "long", "long_edge"]:
                            duplex_setting = "duplexlong"
                        elif duplex_value in ["DuplexTumble", "ShortEdge", "short", "short_edge"]:
                            duplex_setting = "duplexshort"
                        elif duplex_value in ["None", "none", "simplex"]:
                            duplex_setting = "simplex"
                    if duplex_setting:
                        cmd.extend(["-print-settings", duplex_setting])
                    cmd.append(abs_path)
                    result = subprocess.run(
                        cmd,
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                    )
                    if result.returncode != 0:
                        return {"success": False, "message": f"SumatraPDF打印失败: {result.stderr.strip() or result.stdout.strip()}"}
                except Exception as e:
                    return {"success": False, "message": f"SumatraPDF打印失败: {str(e)}"}
            else:
                # 执行打印命令
                # 注意: file_path 必须是绝对路径
                abs_path = os.path.abspath(file_path)
            
            # 核心调用
            # win32api.ShellExecute(0, "printto", abs_path, f'"{printer_name}"', ".", 0)
            
            # 由于 ShellExecute 是异步的且不返回 JobID，我们需要一种机制来猜测 JobID
            # 或者我们先暂停一下，让任务进入队列
            
            # 使用 print 动词（使用默认打印机）可能比 printto 更可靠，但我们需要先设置默认打印机
            res = 33
            if not sumatra_path:
                current_default = win32print.GetDefaultPrinter()
                if current_default != printer_name:
                    print(f"🔄 [INFO] 临时切换默认打印机: {current_default} -> {printer_name}")
                    win32print.SetDefaultPrinter(printer_name)
                    
                try:
                    print(f"🖨️ [INFO] 尝试使用 'print' 动词打印: {abs_path}")
                    res = win32api.ShellExecute(0, "print", abs_path, None, ".", 0)
                    
                    if res <= 32:
                        print(f"⚠️ [WARNING] 'print' 命令失败 (code {res})，尝试 'printto'...")
                        res = win32api.ShellExecute(0, "printto", abs_path, f'"{printer_name}"', ".", 0)
                finally:
                    if current_default != printer_name:
                        print(f"🔄 [INFO] 恢复默认打印机: {current_default}")
                        win32print.SetDefaultPrinter(current_default)
                
                if res <= 32:
                    if res == 31:
                        return {"success": False, "message": "系统未关联PDF阅读器，请安装 Adobe Reader 或 SumatraPDF"}
                    return {"success": False, "message": f"ShellExecute调用失败, 错误码: {res}"}
            
            # 轮询获取打印任务ID - 从任务提交后立即开始检查
            job_id = None
            max_attempts = 5  # 最多尝试5次（0秒、1秒、2秒、3秒、4秒）
            
            for attempt in range(max_attempts):
                try:
                    printer_handle = win32print.OpenPrinter(printer_name)
                    jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
                    win32print.ClosePrinter(printer_handle)
                    
                    if jobs:
                        # 找到ID最大的任务（最新的）
                        latest_job = max(jobs, key=lambda x: x['JobId'])
                        job_id = latest_job['JobId']
                        print(f"✅ [INFO] 获取到打印任务ID: {job_id} (第{attempt+1}次尝试)")
                        break
                    elif attempt < max_attempts - 1:
                        # 还有重试机会，等待1秒后继续
                        time.sleep(1)
                except Exception as e:
                    print(f"⚠️ [WARNING] 第{attempt+1}次获取打印任务ID失败: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(1)
            
            if not job_id:
                print(f"⚠️ [WARNING] {max_attempts}次尝试后仍未获取到job_id，虚拟打印机可能不经过后台程序")
            
            return {
                "success": True, 
                "job_id": job_id, 
                "printer_name": printer_name,
                "file_path": file_path,
                "message": "PDF打印命令已发送"
            }
            
        except Exception as e:
            print(f"❌ [ERROR] PDF打印失败: {e}")
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
            
            # 打开图片并转换为适合打印的格式
            img = Image.open(file_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 创建临时BMP文件（打印机更容易处理）
            with tempfile.NamedTemporaryFile(suffix='.bmp', delete=False) as tmp:
                temp_bmp = tmp.name
                img.save(temp_bmp, 'BMP')
            
            try:
                # 先用win32print获取job_id
                printer_handle = win32print.OpenPrinter(printer_name)
                job_info = (
                    job_name or os.path.basename(file_path),  # pDocName
                    None,  # pOutputFile
                    'RAW'  # pDatatype
                )
                job_id = win32print.StartDocPrinter(printer_handle, 1, job_info)
                
                # 不要立即关闭，保持打印任务活跃状态
                
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
                        
                        if 'color_model' in print_options and print_options['color_model'] != '默认':
                            if print_options['color_model'] == 'Gray':
                                devmode.Color = win32con.DMCOLOR_MONOCHROME
                            else:
                                devmode.Color = win32con.DMCOLOR_COLOR
                            devmode.Fields |= win32con.DM_COLOR
                            
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
                
                # 计算图片缩放
                img_width, img_height = img.size
                scale = min(printer_width / img_width, printer_height / img_height)
                new_width = int(img_width * scale)
                new_height = int(img_height * scale)
                
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
                    
                    # 使用StretchBlt绘制图片
                    hdc.StretchBlt(
                        (0, 0),  # 目标位置
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
                
                # 结束win32print打印任务
                if printer_handle and job_id:
                    win32print.EndDocPrinter(printer_handle)
                    win32print.ClosePrinter(printer_handle)
                    printer_handle = None
                
            except Exception as print_error:
                print(f"打印过程失败: {print_error}")
                if printer_handle:
                    try:
                        if job_id:
                            win32print.EndDocPrinter(printer_handle)
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
            if work_offline and work_offline.lower() in ("true", "1", "yes"):
                return "离线"
            if printer_status == "7" or extended_status == "7" or detected_error_state == "9" or availability == "8":
                return "离线"
            if printer_status == "4" or extended_status == "4":
                return "正在打印"
            if printer_status in ("3", "5") or extended_status in ("3", "5"):
                return "就绪"
            if detected_error_state and detected_error_state not in ("0", "2"):
                return "错误"
            return None
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
            print("⚠️ [WARNING] WMI 打印任务监听器不可用")
    
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
            print("⚠️ [WARNING] WMI不可用，无法启动事件监听")
            return None
        
        if not on_complete:
            print("⚠️ [WARNING] 必须提供 on_complete 回调函数")
            return None
        
        import threading
        
        monitor_key = f"{printer_name}:{job_id}"
        
        def monitor_thread():
            """WMI 事件监听线程"""
            try:
                # COM 初始化（每个线程必须独立初始化）
                pythoncom.CoInitialize()
                
                print(f"🔍 [INFO] 启动 WMI 事件监听: {monitor_key}")
                
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
                
                print(f"✅ [INFO] WMI 监听器已就绪: {monitor_key}")
                
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
                
                print(f"✅ [INFO] WMI 检测到任务完成: {monitor_key}")
                print(f"   └─ 文档: {job_info['document']}")
                print(f"   └─ 页数: {job_info['pages_printed']}/{job_info['total_pages']}")
                
                # 调用完成回调
                if on_complete:
                    on_complete(job_info)
                
            except Exception as e:
                print(f"❌ [ERROR] WMI 监听异常: {monitor_key} - {e}")
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
                print(f"🛑 [INFO] WMI 监听器已停止: {monitor_key}")
        
        # 启动监听线程
        thread = threading.Thread(target=monitor_thread, daemon=True, name=f"WMI-Monitor-{monitor_key}")
        thread.start()
        
        # 记录监听器
        self.monitors[monitor_key] = thread
        
        return monitor_key
    
    def stop_job_monitor(self, monitor_key: str):
        """停止指定的任务监听（注意：WMI 监听是阻塞的，只能等待其自然结束）"""
        if monitor_key in self.monitors:
            print(f"⏸️ [INFO] 请求停止 WMI 监听: {monitor_key}")
            # WMI 的 watch_for 是阻塞的，无法主动中断
            # 只能等待事件触发或线程自然结束
            del self.monitors[monitor_key]
    
    def get_active_monitors(self) -> List[str]:
        """获取当前活跃的监听器列表"""
        return list(self.monitors.keys())
    
    def stop_all(self):
        """停止所有监听器"""
        print(f"🛑 [INFO] 停止所有 WMI 监听器（共 {len(self.monitors)} 个）")
        self.monitors.clear()

