import { Link, Outlet } from "react-router-dom";
import Disclaimer from "./components/Disclaimer";
import { MapProvider } from "./components/MapCanvas";

export default function App() {
  return (
    <MapProvider>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">Pravah <span>flood &amp; landslide decision support</span></Link>
          <nav><Link to="/">Explore</Link></nav>
        </header>
        <Disclaimer />
        <div className="page"><Outlet /></div>
        <footer className="foot tiny">
          © OpenStreetMap contributors (ODbL) · Google Open Buildings (CC BY 4.0) · MERIT Hydro (CC BY-NC 4.0) · Global Flood Database (CC BY-NC 4.0) ·
          WorldPop · CHIRPS · GPM IMERG · Dynamic World · Copernicus DEM · JRC GSW · NASA GLC · Forecast: Google Maps Platform Weather API
        </footer>
      </div>
    </MapProvider>
  );
}
