import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Explore from "./pages/Explore";
import Workspace from "./pages/Workspace";
import "./styles.css";

const router = createBrowserRouter([
  {
    path: "/", element: <App />, children: [
      { index: true, element: <Explore /> },
      { path: "area/:aoiId", element: <Workspace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
