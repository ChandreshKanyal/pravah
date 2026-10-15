import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Advisory from "./pages/Advisory";
import Explore from "./pages/Explore";
import Methods from "./pages/Methods";
import Verify from "./pages/Verify";
import Workspace from "./pages/Workspace";
import "./styles.css";

const router = createBrowserRouter([
  {
    path: "/", element: <App />, children: [
      { index: true, element: <Explore /> },
      { path: "area/:aoiId", element: <Workspace /> },
      { path: "area/:aoiId/advisory", element: <Advisory /> },
      { path: "area/:aoiId/run/:runId/advisory", element: <Advisory /> },
      { path: "area/:aoiId/verify", element: <Verify /> },
      { path: "methods", element: <Methods /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
