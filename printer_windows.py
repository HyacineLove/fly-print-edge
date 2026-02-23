"""
Windows打印机实现
包含所有Windows平台的打印机操作
"""

import platform
import os
from typing import List, Dict, Any

# Windows特定导入
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
        import win32con
        import pywintypes
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
else:
    WIN32_AVAILABLE = False


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
                timeout=30
            )
            return result
        except Exception as e:
            print(f"执行命令失败: {e}")
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
            
            # 调用Word/WPS进行转换
            word = None
            app_name = "Word.Application"
            
            try:
                # 优先尝试调用 WPS
                # WPS文字的ProgID通常是 Kwps.Application 或 WPS.Application
                # 这里尝试几种常见的ProgID
                wps_prog_ids = ["Kwps.Application", "WPS.Application"]
                for prog_id in wps_prog_ids:
                    try:
                        word = client.Dispatch(prog_id)
                        app_name = prog_id
                        print(f"✅ [INFO] 成功连接到 WPS ({prog_id})")
                        break
                    except Exception:
                        continue
                
                # 如果WPS不可用，回退到Microsoft Word
                if not word:
                    # 再次尝试 Kwps.Application (有时候第一遍可能失败)
                    try:
                         word = client.Dispatch("Kwps.Application")
                         app_name = "Kwps.Application"
                         print(f"✅ [INFO] 成功连接到 WPS (Kwps.Application)")
                    except:
                        print("⚠️ [WARNING] 未找到 WPS，尝试调用 Microsoft Word")
                        try:
                            word = client.Dispatch("Word.Application")
                            app_name = "Word.Application"
                        except:
                            # 最后尝试 wps.application (小写)
                            try:
                                word = client.Dispatch("wps.application")
                                app_name = "wps.application"
                            except:
                                pass
            
            except Exception as e:
                print(f"❌ [ERROR] 无法启动文档处理程序 (WPS/Word): {e}")
                raise e

            word.Visible = False
            # WPS可能不支持DisplayAlerts属性，加个try-except
            try:
                word.DisplayAlerts = False
            except:
                pass
            
            try:
                # 兼容路径格式
                abs_file_path = os.path.abspath(file_path)
                doc = word.Documents.Open(abs_file_path)
                
                # wdFormatPDF = 17
                doc.SaveAs(pdf_path, FileFormat=17)
                doc.Close()
                print(f"✅ [INFO] 文档转PDF成功 (使用 {app_name})")
            except Exception as e:
                print(f"❌ [ERROR] 文档转PDF失败: {e}")
                # 尝试关闭文档
                try:
                    doc.Close()
                except:
                    pass
                raise e
            finally:
                try:
                    word.Quit()
                except:
                    pass
                
            # 转换成功后，调用PDF打印逻辑
            return self._print_pdf_file(printer_name, pdf_path, job_name, print_options)
            
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
            
            # 执行打印命令
            # 注意: file_path 必须是绝对路径
            abs_path = os.path.abspath(file_path)
            
            # 核心调用
            # win32api.ShellExecute(0, "printto", abs_path, f'"{printer_name}"', ".", 0)
            
            # 由于 ShellExecute 是异步的且不返回 JobID，我们需要一种机制来猜测 JobID
            # 或者我们先暂停一下，让任务进入队列
            
            # 使用 print 动词（使用默认打印机）可能比 printto 更可靠，但我们需要先设置默认打印机
            current_default = win32print.GetDefaultPrinter()
            if current_default != printer_name:
                print(f"🔄 [INFO] 临时切换默认打印机: {current_default} -> {printer_name}")
                win32print.SetDefaultPrinter(printer_name)
                
            try:
                # 使用 "print" 动词而不是 "printto"
                # "print" 动词更通用，它只是告诉系统"打印这个文件"，系统会调用关联程序的默认打印命令
                # 使用 ShellExecute 的 hwnd 参数设为 0 表示没有父窗口
                # showCmd 设为 0 (SW_HIDE) 尝试隐藏窗口
                
                # 特别注意：对于 Edge 浏览器作为 PDF 阅读器的情况，print 动词可能无效或弹出对话框
                # 推荐安装 SumatraPDF 并将其设为默认，或者关联 PDF 文件
                
                print(f"🖨️ [INFO] 尝试使用 'print' 动词打印: {abs_path}")
                res = win32api.ShellExecute(0, "print", abs_path, None, ".", 0)
                
                if res <= 32:
                    # 如果 print 失败，尝试 printto 作为备选
                    print(f"⚠️ [WARNING] 'print' 命令失败 (code {res})，尝试 'printto'...")
                    res = win32api.ShellExecute(0, "printto", abs_path, f'"{printer_name}"', ".", 0)
            finally:
                # 恢复默认打印机
                if current_default != printer_name:
                    print(f"🔄 [INFO] 恢复默认打印机: {current_default}")
                    win32print.SetDefaultPrinter(current_default)
            
            if res <= 32:
                # 错误码 31 = SE_ERR_NOASSOC (没有关联的程序)
                if res == 31:
                    return {"success": False, "message": "系统未关联PDF阅读器，请安装 Adobe Reader 或 SumatraPDF"}
                return {"success": False, "message": f"ShellExecute调用失败, 错误码: {res}"}
            
            # 等待一小段时间让任务进入Spooler
            time.sleep(2)
            
            # 尝试查找最近的任务作为 JobID
            job_id = 0
            try:
                printer_handle = win32print.OpenPrinter(printer_name)
                # 获取所有任务
                jobs = win32print.EnumJobs(printer_handle, 0, -1, 1)
                win32print.ClosePrinter(printer_handle)
                
                if jobs:
                    # 假设ID最大的就是最新的任务
                    latest_job = max(jobs, key=lambda x: x['JobId'])
                    job_id = latest_job['JobId']
                    print(f"✅ [INFO] 获取到打印任务ID: {job_id}")
            except Exception as e:
                print(f"⚠️ [WARNING] 获取打印任务ID失败: {e}")
            
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