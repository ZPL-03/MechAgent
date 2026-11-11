import { describe, expect, it } from "vitest";
import { english } from "./catalog";
import { translate } from "./translate";

describe("interface translations", () => {
  it("keeps unknown engineering content and Chinese text intact", () => {
    expect(translate("en", "constructor")).toBe("constructor");
    expect(translate("en", "toString")).toBe("toString");
    expect(translate("zh", "深色")).toBe("深色");
    expect(translate("en", "E=210000 MPa, D:/case.inp")).toBe(
      "E=210000 MPa, D:/case.inp",
    );
  });
  it("translates arguments, numbers and dynamic summaries", () => {
    expect(translate("en", "主题：{0}，点击切换", "深色")).toBe(
      "Theme: Dark. Click to switch",
    );
    expect(translate("en", "{0} 节点 / {1} 单元", 0, 80)).toBe(
      "0 nodes / 80 elements",
    );
    expect(translate("en", "真实网格 · 189 节点 / 80 单元")).toBe(
      "Solver mesh · 189 nodes / 80 elements",
    );
    expect(translate("zh", "{0} 节点 / {1} 单元", 189, 80)).toBe(
      "189 节点 / 80 单元",
    );
  });
  it("retains missing arguments and literal replacement characters", () => {
    expect(translate("en", "{0} 节点 / {1} 单元", "$&")).toBe(
      "$& nodes / {1} elements",
    );
  });
  it("preserves every catalog placeholder", () => {
    for (const [source, target] of Object.entries(english)) {
      const placeholders = (value: string) =>
        (value.match(/\{\d+\}/g) ?? []).sort();
      expect(placeholders(target), source).toEqual(placeholders(source));
    }
  });
});
