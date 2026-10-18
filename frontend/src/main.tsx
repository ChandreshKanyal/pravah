import { lazy, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Explore from "./pages/Explore";
import Workspace from "./pages/Workspace";
import "./styles.css";

// Secondary pages load on demand (the 3D view pulls in deck.gl geo layers).
const Advisory = lazy(() => import("./pages/Advisory"));
const Methods = lazy(() => import("./pages/Methods"));
const View3D = lazy(() => import("./pages/View3D"));
const Projects = lazy(() => import("./pages/Projects"));
const Drill = lazy(() => import("./pages/Drill"));
const S = (el: ReactNode) => <Suspense fallback={<div className="lin indet" style={{ position: "absolute", top: 0, left: 0, right: 0 }}><i /></div>}>{el}</Suspense>;

const router = createBrowserRouter([
  {
    path: "/", element: <App />, children: [
      { index: true, element: <Explore /> },
      { path: "area/:aoiId", element: <Workspace /> },
      { path: "area/:aoiId/advisory", element: S(<Advisory />) },
      { path: "area/:aoiId/run/:runId/advisory", element: S(<Advisory />) },
      { path: "area/:aoiId/3d", element: S(<View3D />) },
      { path: "area/:aoiId/drill", element: S(<Drill />) },
      { path: "methods", element: S(<Methods />) },
      { path: "projects", element: S(<Projects />) },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
