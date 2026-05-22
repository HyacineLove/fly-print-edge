export function capabilityLabel(value) {
  if (value === true) return "支持";
  if (value === false) return "不支持";
  return "未知";
}

export function printerCapabilitySummary(item) {
  if (item?.capability_summary) {
    return item.capability_summary;
  }
  return `单双面: ${capabilityLabel(item?.duplex_supported)}, 彩色: ${capabilityLabel(item?.color_supported)}`;
}
