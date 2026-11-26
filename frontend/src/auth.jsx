import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  AUTH_EXPIRED_EVENT,
  TOKEN_STORAGE_KEY,
} from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const navigate = useNavigate();
  const [token, setToken] = useState(() =>
    window.sessionStorage.getItem(TOKEN_STORAGE_KEY),
  );
  const [student, setStudent] = useState(null);
  const [loading, setLoading] = useState(
    () => Boolean(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)),
  );
  const [sessionError, setSessionError] = useState("");
  const [verificationAttempt, setVerificationAttempt] = useState(0);

  const clearSession = useCallback(
    (redirect = false) => {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      setToken(null);
      setStudent(null);
      setLoading(false);
      setSessionError("");
      if (redirect) {
        navigate("/login", {
          replace: true,
          state: { notice: "Your session expired. Please sign in again." },
        });
      }
    },
    [navigate],
  );

  const onAuthExpired = useCallback(() => {
    clearSession(true);
  }, [clearSession]);

  useEffect(() => {
    window.addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
    };
  }, [onAuthExpired]);

  useEffect(() => {
    if (!token) {
      setStudent(null);
      setLoading(false);
      setSessionError("");
      return undefined;
    }

    let active = true;
    setLoading(true);
    setSessionError("");
    api
      .getProfile(token)
      .then(({ data }) => {
        if (active) {
          setStudent(data);
          setSessionError("");
        }
      })
      .catch((error) => {
        if (error.status === 401) {
          clearSession(true);
        } else if (active) {
          setStudent(null);
          setSessionError(error.message);
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [token, verificationAttempt, clearSession]);

  const login = useCallback(async (credentials) => {
    const { data } = await api.login(credentials);
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, data.access_token);
    setStudent(null);
    setLoading(true);
    setSessionError("");
    setToken(data.access_token);
  }, []);

  const logout = useCallback(() => {
    clearSession(false);
    navigate("/login", { replace: true, state: { notice: "You have signed out." } });
  }, [clearSession, navigate]);

  const retryProfile = useCallback(() => {
    setVerificationAttempt((attempt) => attempt + 1);
  }, []);

  const value = useMemo(
    () => ({
      student,
      token,
      loading,
      sessionError,
      login,
      logout,
      retryProfile,
    }),
    [student, token, loading, sessionError, login, logout, retryProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
