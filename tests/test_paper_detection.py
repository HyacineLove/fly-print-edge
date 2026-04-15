"""
测试纸张尺寸自动检测功能
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter

def test_pdf_detection():
    """测试 PDF 文件尺寸检测"""
    printer = WindowsEnterprisePrinter()
    
    # 测试不同的 PDF 文件
    test_files = [
        "A4 文档.pdf",
        "Letter 文档.pdf",
        "A3 文档.pdf"
    ]
    
    for file_name in test_files:
        if os.path.exists(file_name):
            print(f"\n测试 PDF: {file_name}")
            detected = printer._detect_pdf_page_size(file_name)
            print(f"  检测结果：{detected}")
        else:
            print(f"\n跳过 (文件不存在): {file_name}")

def test_word_detection():
    """测试 Word 文档尺寸检测"""
    printer = WindowsEnterprisePrinter()
    
    test_files = [
        "A4 文档.docx",
        "Letter 文档.docx"
    ]
    
    for file_name in test_files:
        if os.path.exists(file_name):
            print(f"\n测试 Word: {file_name}")
            detected = printer._detect_word_document_size(file_name)
            print(f"  检测结果：{detected}")
        else:
            print(f"\n跳过 (文件不存在): {file_name}")

def test_identify_paper_size():
    """测试纸张尺寸识别函数"""
    printer = WindowsEnterprisePrinter()
    
    test_cases = [
        (8.27, 11.69, "A4"),      # A4
        (8.5, 11.0, "Letter"),    # Letter
        (11.69, 16.54, "A3"),     # A3
        (5.83, 8.27, "A5"),       # A5
        (8.5, 14.0, "Legal"),     # Legal
    ]
    
    print("\n\n测试纸张尺寸识别:")
    for width, height, expected in test_cases:
        result = printer._identify_paper_size(width, height)
        status = "✓" if expected in result else "✗"
        print(f"  {status} {width}x{height}英寸 -> {result} (期望：{expected})")

if __name__ == "__main__":
    print("=" * 60)
    print("纸张尺寸自动检测功能测试")
    print("=" * 60)
    
    test_identify_paper_size()
    test_pdf_detection()
    test_word_detection()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
