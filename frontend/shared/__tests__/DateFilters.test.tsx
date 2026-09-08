import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DateFilters, FiltersProvider, useFilters } from "../ui";

// Exposes the committed filters as text so assertions can read exactly what
// reached FiltersContext (and therefore every page's react-query key),
// distinct from whatever is currently typed into the still-open popover.
function CommittedRange() {
  const { filters } = useFilters();
  return <div data-testid="committed-range">{filters.date_from}..{filters.date_to}</div>;
}

function renderDateFilters() {
  return render(
    <FiltersProvider>
      <DateFilters />
      <CommittedRange />
    </FiltersProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("DateFilters custom range popover", () => {
  it("does not apply or close the popover after editing only one field", async () => {
    renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);

    const before = screen.getByTestId("committed-range").textContent;

    const fromInput = screen.getByLabelText("С") as HTMLInputElement;
    fireEvent.change(fromInput, { target: { value: "2026-05-01" } });

    // Still open: the popover dialog must remain in the document.
    expect(screen.getByRole("dialog", { name: "Выбор периода" })).toBeInTheDocument();
    // Still uncommitted: FiltersContext must not have changed from a
    // single-field edit (the old buggy useEffect fired setRange() here).
    expect(screen.getByTestId("committed-range").textContent).toBe(before);
  });

  it("applies the range as one atomic update only after both dates are set and Apply is clicked", async () => {
    renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);

    const fromInput = screen.getByLabelText("С") as HTMLInputElement;
    const toInput = screen.getByLabelText("По") as HTMLInputElement;
    fireEvent.change(fromInput, { target: { value: "2026-05-01" } });
    fireEvent.change(toInput, { target: { value: "2026-05-10" } });

    // Still not applied merely by typing into both fields.
    expect(screen.getByTestId("committed-range").textContent).not.toBe("2026-05-01..2026-05-10");

    const applyButton = screen.getByRole("button", { name: "Применить" });
    expect(applyButton).toBeEnabled();
    await userEvent.click(applyButton);

    expect(screen.getByTestId("committed-range").textContent).toBe("2026-05-01..2026-05-10");
    // Popover closes only once a valid range has actually been applied.
    expect(screen.queryByRole("dialog", { name: "Выбор периода" })).not.toBeInTheDocument();
  });

  it("disables Apply when From is after To, and never silently swaps them", async () => {
    renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);

    const fromInput = screen.getByLabelText("С") as HTMLInputElement;
    const toInput = screen.getByLabelText("По") as HTMLInputElement;
    fireEvent.change(fromInput, { target: { value: "2026-06-20" } });
    fireEvent.change(toInput, { target: { value: "2026-06-10" } });

    const applyButton = screen.getByRole("button", { name: "Применить" });
    expect(applyButton).toBeDisabled();

    const before = screen.getByTestId("committed-range").textContent;
    fireEvent.click(applyButton);
    expect(screen.getByTestId("committed-range").textContent).toBe(before);
  });

  it("disables Apply when a field is empty", async () => {
    renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);

    const fromInput = screen.getByLabelText("С") as HTMLInputElement;
    fireEvent.change(fromInput, { target: { value: "" } });

    expect(screen.getByRole("button", { name: "Применить" })).toBeDisabled();
  });

  it("still applies quick presets (e.g. last 7 days) with a single click", async () => {
    renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);

    await userEvent.click(screen.getByRole("button", { name: /Последние 7 дней/ }));

    expect(screen.queryByRole("dialog", { name: "Выбор периода" })).not.toBeInTheDocument();
    const [from, to] = screen.getByTestId("committed-range").textContent!.split("..");
    expect(from <= to).toBe(true);
  });

  it("persists the applied custom range across a remount (cross-page persistence via localStorage)", async () => {
    const first = renderDateFilters();
    const trigger = screen.getAllByRole("button", { expanded: false })[0];
    await userEvent.click(trigger);
    fireEvent.change(screen.getByLabelText("С"), { target: { value: "2026-03-01" } });
    fireEvent.change(screen.getByLabelText("По"), { target: { value: "2026-03-15" } });
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(screen.getByTestId("committed-range").textContent).toBe("2026-03-01..2026-03-15");
    first.unmount();

    // Simulates navigating to a different page: a fresh FiltersProvider
    // mount must pick the same range back up from localStorage.
    renderDateFilters();
    expect(screen.getByTestId("committed-range").textContent).toBe("2026-03-01..2026-03-15");
  });
});
