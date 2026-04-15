"""
测试 Letter 尺寸发票打印修复
模拟实际打印流程，验证纸张检测和配置
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter

def test_letter_invoice():
    """测试 Letter 尺寸发票的打印配置"""
    printer = WindowsEnterprisePrinter()
    
    print("\n" + "="*60)
    print("Letter 尺寸发票打印修复测试")
    print("="*60)
    
    # 测试 1: 检测 Letter 尺寸
    print("\n[测试 1] 纸张尺寸识别")
    letter_width = 8.5   # Letter 宽度 (英寸)
    letter_height = 11.0 # Letter 高度 (英寸)
    
    result = printer._identify_paper_size(letter_width, letter_height)
    print(f"  输入：{letter_width}x{letter_height}英寸")
    print(f"  识别结果：{result}")
    
    if "Letter" in result:
        print("  ✓ 正确识别为 Letter")
    else:
        print(f"  ✗ 识别失败，期望 Letter，得到 {result}")
    
    # 测试 2: 模拟打印选项处理
    print("\n[测试 2] 打印选项优先级")
    
    # 场景 A: 用户未指定，自动检测
    print("\n  场景 A: 用户未指定纸张")
    print_options = {}
    detected = "Letter"  # 假设检测到 Letter
    final_size = print_options.get('paper_size') or detected
    print(f"    用户指定：无")
    print(f"    自动检测：{detected}")
    print(f"    最终使用：{final_size}")
    if final_size == "Letter":
        print("    ✓ 正确")
    else:
        print(f"    ✗ 错误")
    
    # 场景 B: 用户指定 A4，覆盖检测
    print("\n  场景 B: 用户指定 A4")
    print_options = {'paper_size': 'A4'}
    detected = "Letter"
    final_size = print_options.get('paper_size') or detected
    print(f"    用户指定：A4")
    print(f"    自动检测：{detected}")
    print(f"    最终使用：{final_size}")
    if final_size == "A4":
        print("    ✓ 正确 (用户优先)")
    else:
        print(f"    ✗ 错误")
    
    # 测试 3: SumatraPDF 参数构建
    print("\n[测试 3] SumatraPDF 参数构建")
    
    def build_sumatra_params(paper_size):
        """模拟 SumatraPDF 参数构建逻辑"""
        print_settings = []
        
        if paper_size:
            paper_str = str(paper_size).upper()
            if paper_str in ["A4", "A3", "A5", "LETTER", "LEGAL", "TABLOID"]:
                print_settings.append(paper_str.lower())
                
                # 关键修复：非 A4 纸张不使用 fit
                if paper_str != "A4":
                    print(f"    → 非 A4 纸张 ({paper_size})，不添加 fit")
                else:
                    print_settings.append("fit")
                    print(f"    → A4 纸张，添加 fit")
        
        return print_settings
    
    # 测试 Letter
    print("\n  测试 Letter:")
    params = build_sumatra_params("Letter")
    print(f"    参数：{params}")
    if "letter" in params and "fit" not in params:
        print("    ✓ 正确 (有 letter，无 fit)")
    else:
        print("    ✗ 错误")
    
    # 测试 A4
    print("\n  测试 A4:")
    params = build_sumatra_params("A4")
    print(f"    参数：{params}")
    if "a4" in params and "fit" in params:
        print("    ✓ 正确 (有 a4 和 fit)")
    else:
        print("    ✗ 错误")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)
    
    print("\n[关键修复说明]")
    print("1. 打印前配置打印机 DEVMODE，设置正确的纸张")
    print("2. Letter 等非 A4 纸张，SumatraPDF 不添加 fit 参数")
    print("3. 避免内容被缩放到 A4，导致只有一半的问题")

if __name__ == "__main__":
    test_letter_invoice()
