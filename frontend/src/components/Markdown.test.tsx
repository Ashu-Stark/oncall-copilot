import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders italics, code and bold without breaking on snake_case names", () => {
    const { container } = render(<Markdown source={"_Not resolved yet._\n\n**Truth:** fault `db_down` in hoi_platform"} />);
    expect(container.querySelector("em")?.textContent).toBe("Not resolved yet.");
    expect(container.querySelector("code")?.textContent).toBe("db_down");
    expect(container.textContent).toContain("hoi_platform");
    expect(container.querySelectorAll("em")).toHaveLength(1);
  });

  it("never turns incident text into HTML", () => {
    const { container } = render(<Markdown source={"<img src=x onerror=alert(1)>"} />);
    expect(container.querySelector("img")).toBeNull();
  });
});
