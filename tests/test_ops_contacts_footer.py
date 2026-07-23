def format_ops_contacts_footer(contacts):
    if not isinstance(contacts, list) or not contacts:
        return ""
    lines = []
    for item in contacts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        phone = str(item.get("phone") or "").strip()
        if name and phone:
            lines.append(f"{name} {phone}")
    return "\n".join(lines)


def normalize_ops_contacts(raw_contacts):
    if not isinstance(raw_contacts, list):
        return []
    contacts = []
    for item in raw_contacts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        phone = str(item.get("phone") or "").strip()
        if name and phone:
            contacts.append({"name": name, "phone": phone})
    return contacts


def test_format_ops_contacts_footer():
    assert format_ops_contacts_footer([]) == ""
    assert format_ops_contacts_footer([{"name": "张三", "phone": "13800000000"}]) == "张三 13800000000"
    assert (
        format_ops_contacts_footer(
            [
                {"name": "张三", "phone": "13800000000"},
                {"name": "李四", "phone": "13900000000"},
            ]
        )
        == "张三 13800000000\n李四 13900000000"
    )


def test_normalize_ops_contacts():
    assert normalize_ops_contacts([{"name": " 张三 ", "phone": " 138 "}, {"name": "", "phone": "1"}, "x"]) == [
        {"name": "张三", "phone": "138"}
    ]
