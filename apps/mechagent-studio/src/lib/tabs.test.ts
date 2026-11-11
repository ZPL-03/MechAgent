import { expect, it } from "vitest";
import type { KeyboardEvent } from "react";
import { handleTabKeyDown } from "./tabs";

it.each([
  ["ArrowRight", 2, 0],
  ["ArrowLeft", 0, 2],
  ["Home", 2, 0],
  ["End", 0, 2],
])("%s moves focus and selection together", (key, current, expected) => {
  let focused = -1;
  let selected = -1;
  let prevented = false;
  const tabs = [0, 1, 2].map((index) => ({
    focus: () => {
      focused = index;
    },
    click: () => {
      selected = index;
    },
  }));
  const event = {
    key,
    target: tabs[current],
    currentTarget: { querySelectorAll: () => tabs },
    preventDefault: () => {
      prevented = true;
    },
  } as unknown as KeyboardEvent<HTMLElement>;
  handleTabKeyDown(event);
  expect([focused, selected, prevented]).toEqual([expected, expected, true]);
});

it("leaves ordinary typing untouched", () => {
  handleTabKeyDown({ key: "a" } as KeyboardEvent<HTMLElement>);
});
