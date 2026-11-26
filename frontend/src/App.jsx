import React from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
} from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import BookingHistoryPage from "./pages/BookingHistoryPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import RegistrationPage from "./pages/RegistrationPage";

function LoadingScreen({ children = "Preparing your student account…" }) {
  return (
    <div className="loading-panel" role="status">
      <span className="spinner" aria-hidden="true" />
      {children}
    </div>
  );
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
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link aria-label="Campus Play home" className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">CP</span>
          <span className="brand-copy">
            <strong>Campus Play</strong>
            <small>Sports venue booking</small>
          </span>
        </Link>
        <nav aria-label="Main navigation" className="main-nav">
          {student ? (
            <>
              <Link to="/">Book a court</Link>
              <Link to="/bookings">My bookings</Link>
              <span className="student-greeting">
                <span className="avatar" aria-hidden="true">{student.usn?.slice(-2) ?? "ST"}</span>
                <span>{student.usn}</span>
              </span>
              <button className="nav-logout" onClick={logout} type="button">Sign out</button>
            </>
          ) : (
            <>
              <Link to="/login">Sign in</Link>
              <Link className="nav-register" to="/register">Create account</Link>
            </>
          )}
        </nav>
      </header>
      <main className="main-content">
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
            <Route element={<DashboardPage />} path="/" />
            <Route element={<BookingHistoryPage />} path="/bookings" />
          </Route>
          <Route element={<Navigate replace to="/" />} path="*" />
        </Routes>
      </main>
      <footer className="site-footer">
        <span>Campus Play</span>
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
