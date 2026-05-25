import { render, screen } from "@testing-library/react";

import App from "../App";

describe("App", () => {
  it("renders the launch shell before a session exists", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: /a more transparent workspace for wind resource assessment/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start analysis workspace/i })).toBeInTheDocument();
    expect(screen.getByText(/^open-source attempt$/i)).toBeInTheDocument();
    expect(screen.getByText(/what it is trying to achieve/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /what is online right now/i })).toBeInTheDocument();
  });
});