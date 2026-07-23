from cloud_service import CloudService


def test_normalize_ops_contacts_filters_invalid_rows():
    service = CloudService({})
    assert service._normalize_ops_contacts(
        [
            {"name": "张三", "phone": "13800000000"},
            {"name": "", "phone": "1"},
            {"name": "李四"},
            "bad",
        ]
    ) == [{"name": "张三", "phone": "13800000000"}]
