"""
打印机参数解析器架构
支持多种品牌打印机的参数解析
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class PrinterParameterParser:
    """打印机参数解析器基类"""
    
    def can_handle(self, printer_name: str, output: str) -> bool:
        """判断是否可以处理该打印机的输出格式"""
        raise NotImplementedError
    
    def get_priority(self) -> int:
        """获取解析器优先级，数字越小优先级越高"""
        return 100  # 默认优先级
    
    def parse(self, output: str) -> Dict[str, Any]:
        """解析lpoptions输出，返回标准化的参数格式"""
        raise NotImplementedError
    
    def parse_line(self, line: str) -> tuple:
        """解析单行参数，返回(选项名, 选项值列表)"""
        if ':' not in line:
            return None, None
            
        option_part, values_part = line.split(':', 1)
        option_name = option_part.split('/')[0].strip()
        values = values_part.strip().split()
        
        # 提取选项值（去掉*默认标记）
        clean_values = []
        for value in values:
            clean_value = value.lstrip('*')
            if clean_value:
                clean_values.append(clean_value)
        
        return option_name, clean_values


class HitiParser(PrinterParameterParser):
    """Hiti品牌打印机专用解析器（如P525L照片打印机）"""
    
    def can_handle(self, printer_name: str, output: str) -> bool:
        """通过打印机名称识别Hiti品牌"""
        return "P525L" in printer_name or "hiti" in printer_name.lower()
    
    def get_priority(self) -> int:
        return 10  # 高优先级
    
    def parse(self, output: str) -> Dict[str, Any]:
        """解析Hiti打印机的参数"""
        logger.debug("Using HitiParser for printer capabilities")
        capabilities = {
            "resolution": ["Fast", "Normal", "Best"],
            "page_size": ["A4", "Letter", "Legal"],
            "duplex": ["None"],
            "color_model": ["Color", "Grayscale", "BlackAndWhite"],
            "media_type": ["Plain", "Photo"]
        }
        
        try:
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                logger.debug("Hiti option line: %s", line)
                option_name, clean_values = self.parse_line(line)
                
                if not option_name or not clean_values:
                    continue
                
                option_lower = option_name.lower()
                
                # Hiti P525L专用参数映射
                if 'hpoutputquality' in option_lower or 'printquality' in option_lower:
                    capabilities["resolution"] = clean_values
                    logger.debug("Hiti resolution options: %s", clean_values)
                elif 'pagesize' in option_lower or 'media size' in option_lower:
                    capabilities["page_size"] = clean_values
                    logger.debug("Hiti page size options: %s", clean_values)
                elif 'hpcoloroutput' in option_lower or 'colormode' in option_lower:
                    capabilities["color_model"] = clean_values
                    logger.debug("Hiti color options: %s", clean_values)
                elif 'mediatype' in option_lower or 'papertype' in option_lower:
                    capabilities["media_type"] = clean_values
                    logger.debug("Hiti media type options: %s", clean_values)
                elif 'hppapersource' in option_lower:
                    # Hiti特有的纸张来源（卷纸/手动）
                    capabilities["paper_source"] = clean_values
                    logger.debug("Hiti paper source options: %s", clean_values)
                    
        except Exception as e:
            logger.debug("HitiParser failed", exc_info=True)
        
        return capabilities


class HPParser(PrinterParameterParser):
    """HP品牌打印机专用解析器"""
    
    def can_handle(self, printer_name: str, output: str) -> bool:
        """通过打印机名称识别HP品牌"""
        return "hp" in printer_name.lower() and "laserjet" in printer_name.lower()
    
    def get_priority(self) -> int:
        return 20  # 中等优先级
    
    def parse(self, output: str) -> Dict[str, Any]:
        """解析HP打印机的参数"""
        logger.debug("Using HPParser for printer capabilities")
        capabilities = {
            "resolution": ["300dpi", "600dpi", "1200dpi"],
            "page_size": ["A4", "Letter", "Legal"],
            "duplex": ["None", "DuplexNoTumble", "DuplexTumble"],
            "color_model": ["Gray", "RGB"],
            "media_type": ["Plain", "Cardstock", "Transparency"]
        }
        
        try:
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                logger.debug("HP option line: %s", line)
                option_name, clean_values = self.parse_line(line)
                
                if not option_name or not clean_values:
                    continue
                
                option_lower = option_name.lower()
                
                # HP打印机参数映射
                if 'resolution' in option_lower:
                    capabilities["resolution"] = clean_values
                    logger.debug("HP resolution options: %s", clean_values)
                elif 'pagesize' in option_lower or 'papersize' in option_lower:
                    capabilities["page_size"] = clean_values
                    logger.debug("HP page size options: %s", clean_values)
                elif 'duplex' in option_lower:
                    capabilities["duplex"] = clean_values
                    logger.debug("HP duplex options: %s", clean_values)
                elif 'colormodel' in option_lower:
                    capabilities["color_model"] = clean_values
                    logger.debug("HP color options: %s", clean_values)
                elif 'mediatype' in option_lower:
                    capabilities["media_type"] = clean_values
                    logger.debug("HP media type options: %s", clean_values)
                    
        except Exception as e:
            logger.debug("HPParser failed", exc_info=True)
        
        return capabilities


class GenericCUPSParser(PrinterParameterParser):
    """通用CUPS解析器（兜底方案）"""
    
    def can_handle(self, printer_name: str, output: str) -> bool:
        """总是能处理，作为兜底方案"""
        return True
    
    def get_priority(self) -> int:
        return 100  # 最低优先级
    
    def parse(self, output: str) -> Dict[str, Any]:
        """通用CUPS参数解析（保留原有逻辑）"""
        logger.debug("Using GenericCUPSParser for printer capabilities")
        capabilities = {
            "resolution": ["300dpi", "600dpi", "1200dpi"],
            "page_size": ["A4", "Letter", "Legal"],
            "duplex": ["None", "DuplexNoTumble", "DuplexTumble"],
            "color_model": ["Gray", "RGB"],
            "media_type": ["Plain", "Cardstock", "Transparency"]
        }
        
        try:
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                logger.debug("Generic option line: %s", line)
                option_name, clean_values = self.parse_line(line)
                
                if not option_name or not clean_values:
                    continue
                
                option_lower = option_name.lower()
                
                # 通用参数映射（原有逻辑）
                if 'resolution' in option_lower or 'printquality' in option_lower:
                    capabilities["resolution"] = clean_values
                    logger.debug("Generic resolution options: %s", clean_values)
                elif 'pagesize' in option_lower or 'papersize' in option_lower or 'media size' in option_lower:
                    capabilities["page_size"] = clean_values
                    logger.debug("Generic page size options: %s", clean_values)
                elif 'duplex' in option_lower:
                    capabilities["duplex"] = clean_values
                    logger.debug("Generic duplex options: %s", clean_values)
                elif 'colormodel' in option_lower or 'colormode' in option_lower or 'output mode' in option_lower:
                    capabilities["color_model"] = clean_values
                    logger.debug("Generic color options: %s", clean_values)
                elif 'mediatype' in option_lower or 'media type' in option_lower:
                    capabilities["media_type"] = clean_values
                    logger.debug("Generic media type options: %s", clean_values)
                    
        except Exception as e:
            logger.debug("GenericCUPSParser failed", exc_info=True)
        
        return capabilities


class PrinterParameterParserManager:
    """打印机参数解析器管理器"""
    
    def __init__(self):
        # 按优先级排序的解析器列表
        self.parsers = [
            HitiParser(),
            HPParser(),
            GenericCUPSParser()  # 兜底解析器
        ]
        # 按优先级排序
        self.parsers.sort(key=lambda p: p.get_priority())
        logger.debug("Printer parser manager initialized: parser_count=%s", len(self.parsers))
    
    def get_capabilities(self, printer_name: str, lpoptions_output: str) -> Dict[str, Any]:
        """获取打印机参数，自动选择合适的解析器"""
        logger.debug("Selecting parser for printer: %s", printer_name)
        
        for parser in self.parsers:
            if parser.can_handle(printer_name, lpoptions_output):
                parser_name = parser.__class__.__name__
                logger.debug("Selected parser: %s", parser_name)
                return parser.parse(lpoptions_output)
        
        # 理论上不会到这里，因为GenericCUPSParser总是能处理
        logger.debug("No specialized parser matched; using fallback defaults")
        return {
            "resolution": ["300dpi", "600dpi", "1200dpi"],
            "page_size": ["A4", "Letter", "Legal"],
            "duplex": ["None"],
            "color_model": ["Gray", "RGB"],
            "media_type": ["Plain"]
        }
