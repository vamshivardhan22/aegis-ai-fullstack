import { useAuthContext } from "../context/AuthContext.jsx";
import { registerAccount } from "../lib/api.js";

export function useAuth() {
  const auth = useAuthContext();

  const register = async (credentials) => {
    try {
      await registerAccount(credentials);
      await auth.login({ email: credentials.email, password: credentials.password });
      return { success: true };
    } catch (error) {
      return { success: false, error };
    }
  };

  return { ...auth, register };
}
