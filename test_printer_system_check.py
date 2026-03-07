"""
测试打印机检测和参数传递
"""
import sys
sys.path.insert(0, '.')

from printer_windows import WindowsEnterprisePrinter

# 创建打印机实例
printer = WindowsEnterprisePrinter()

# 测试1: 列出所有系统打印机
print("=" * 60)
print("系统已安装的打印机:")
print("=" * 60)
printers = printer.discover_printers()
for p in printers:
    print(f"   {p['name']}")
    print(f"    类型: {p['type']}")
    if p['type'] == 'network':
        print(f"    端口: {p.get('port', 'N/A')}")

# 测试2: 检查特定打印机是否安装
print("\n" + "=" * 60)
print("检查打印机安装状态:")
print("=" * 60)

test_printers = [
    "KONICA MINOLTA bizhub 2200P",
    "HP Smart Universal Printer",
    "不存在的打印机"
]

import win32print
for name in test_printers:
    try:
        h = win32print.OpenPrinter(name)
        win32print.ClosePrinter(h)
        print(f" {name} - 已安装")
    except:
        print(f" {name} - 未安装")

print("\n" + "=" * 60)
print("建议:")
print("=" * 60)
print("如果您的打印机已安装在系统中，请在配置中使用打印机名称")
print("示例配置:")
print("""
{
  "managed_printers": [
    {
      "id": "printer-1",
      "name": "KONICA MINOLTA bizhub 2200P",
      "enabled": true
    }
  ]
}
""")
print("\n这样就可以正常传递打印参数（双面、彩色等）！")
