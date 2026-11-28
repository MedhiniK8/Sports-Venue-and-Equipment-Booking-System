import React from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import AboutUsPage from "./pages/AboutUsPage";
import AdminPage from "./pages/AdminPage";
import BookingHistoryPage from "./pages/BookingHistoryPage";
import CourtBookingPage from "./pages/DashboardPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import RegistrationPage from "./pages/RegistrationPage";
import SettingsPage from "./pages/SettingsPage";

function LoadingScreen({ children = "Preparing your student account…" }) {
  return (
    <div className="loading-panel" role="status">
      <span className="spinner" aria-hidden="true" />
      {children}
    </div>
  );
}

function ExploreRedirect() {
  const navigate = useNavigate();
  React.useEffect(() => {
    navigate("/", { replace: true, state: { scrollToExplore: true } });
  }, [navigate]);
  return null;
}

function RequireStudent() {
  const { student, loading, sessionError, retryProfile, logout } = useAuth();

  if (loading) {
    return <LoadingScreen>Verifying your session…</LoadingScreen>;
  }
  if (sessionError) {
    return (
      <section className="session-recovery">
        <span className="dialog-mark" aria-hidden="true">!</span>
        <h1>We couldn’t verify your session.</h1>
        <p>{sessionError}</p>
        <div className="inline-actions">
          <button className="button button-primary" onClick={retryProfile} type="button">Retry</button>
          <button className="button button-quiet" onClick={logout} type="button">Sign in again</button>
        </div>
      </section>
    );
  }
  if (!student) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

function RequireAdmin() {
  const { student } = useAuth();
  if (!student) return <Navigate to="/login" replace />;
  if (student.role !== "ADMIN") return <Navigate to="/" replace />;
  return <Outlet />;
}

function PublicOnly({ children }) {
  const { student, loading } = useAuth();
  if (loading) {
    return <LoadingScreen />;
  }
  if (student) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function SiteLayout() {
  const { student, logout } = useAuth();
  const [menuOpen, setMenuOpen] = React.useState(false);

  React.useEffect(() => {
    if (!menuOpen) return undefined;
    function closeOnEscape(event) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  return (
    <div className="app-shell">
      {student ? (
        <>
          <header className="authenticated-header">
            <button
              aria-expanded={menuOpen}
              aria-label="Open navigation"
              className="menu-button"
              onClick={() => setMenuOpen(true)}
              type="button"
            >
              <span />
              <span />
              <span />
            </button>
            <Link aria-label="SportsHub home" className="brand brand-header" to="/">
              <img alt="" src="/images/branding/sportshub-logo.svg" />
              <span className="brand-copy">
                <strong>SportsHub</strong>
                <small>University Sports Booking</small>
              </span>
            </Link>
          </header>
          {menuOpen && (
            <button
              aria-label="Close navigation backdrop"
              className="sidebar-backdrop"
              onClick={() => setMenuOpen(false)}
              type="button"
            />
          )}
          <aside className={`app-sidebar${menuOpen ? " is-open" : ""}`} aria-hidden={!menuOpen}>
            <div className="sidebar-top">
              <Link aria-label="SportsHub home" className="brand" to="/" onClick={() => setMenuOpen(false)}>
                <img alt="" src="/images/branding/sportshub-logo.svg" />
                <span className="brand-copy">
                  <strong>SportsHub</strong>
                  <small>University Sports Booking</small>
                </span>
              </Link>
              <button aria-label="Close navigation" className="sidebar-close" onClick={() => setMenuOpen(false)} type="button">×</button>
            </div>
            <nav aria-label="Main navigation" className="sidebar-nav">
              <NavLink end to="/" onClick={() => setMenuOpen(false)}>Home</NavLink>
              <NavLink to="/explore" onClick={() => setMenuOpen(false)}>Explore</NavLink>
              <NavLink to="/court-booking" onClick={() => setMenuOpen(false)}>Court Booking</NavLink>
              <NavLink to="/bookings" onClick={() => setMenuOpen(false)}>My Bookings</NavLink>
              <NavLink to="/settings" onClick={() => setMenuOpen(false)}>Settings</NavLink>
              <NavLink to="/about" onClick={() => setMenuOpen(false)}>About Us</NavLink>
              {student.role === "ADMIN" && (
                <NavLink to="/admin" onClick={() => setMenuOpen(false)}>Admin</NavLink>
              )}
            </nav>
            <button className="nav-logout sidebar-logout" onClick={logout} type="button">Logout</button>
          </aside>
        </>
      ) : (
        <header className="site-header">
          <Link aria-label="SportsHub home" className="brand" to="/login">
            <img alt="" src="/images/branding/sportshub-logo.svg" />
            <span className="brand-copy">
              <strong>Campus Play</strong>
              <small>Sports venue booking</small>
            </span>
          </Link>
          <nav aria-label="Public navigation" className="main-nav">
            <Link to="/login">Sign in</Link>
            <Link className="nav-register" to="/register">Create account</Link>
          </nav>
        </header>
      )}
      <main className={student ? "main-content protected-content" : "main-content"}>
        <Routes>
          <Route
            element={
              <PublicOnly>
                <LoginPage />
              </PublicOnly>
            }
            path="/login"
          />
          <Route
            element={
              <PublicOnly>
                <RegistrationPage />
              </PublicOnly>
            }
            path="/register"
          />
          <Route element={<RequireStudent />}>
            <Route element={<HomePage />} path="/" />
            <Route element={<ExploreRedirect />} path="/explore" />
            <Route element={<CourtBookingPage />} path="/court-booking" />
            <Route element={<BookingHistoryPage />} path="/bookings" />
            <Route element={<SettingsPage />} path="/settings" />
            <Route element={<AboutUsPage />} path="/about" />
            <Route element={<RequireAdmin />}>
              <Route element={<AdminPage />} path="/admin" />
            </Route>
          </Route>
          <Route element={<Navigate replace to="/" />} path="*" />
        </Routes>
      </main>
      <footer className="site-footer">
        <span>SportsHub</span>
        <span>Venue times shown in Asia/Kolkata</span>
      </footer>
    </div>
  );
}

export function AppRoutes() {
  return (
    <AuthProvider>
      <SiteLayout />
    </AuthProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
