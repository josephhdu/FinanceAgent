import { useAuth } from "./auth/AuthContext";
import { Login } from "./components/Login";
import { Dashboard } from "./components/Dashboard";

export function App() {
  const { token } = useAuth();
  return token ? <Dashboard /> : <Login />;
}
