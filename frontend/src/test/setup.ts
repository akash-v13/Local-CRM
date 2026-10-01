// Adds DOM matchers like toBeInTheDocument() and cleans up rendered components between tests.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
