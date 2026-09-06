import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { queryClient } from "./app/queryClient";
import { router } from "./app/router";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from the template");

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
