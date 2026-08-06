import axios from "axios";

export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({ baseURL: API_URL, timeout: 10000 });

export async function registerAccount({ email, password, full_name, role }) {
  const { data } = await api.post("/auth/register", { email, password, full_name, role });
  return data;
}

export const tokenStore = {
  get: () => localStorage.getItem("aegis_token"),
  set: (token) => localStorage.setItem("aegis_token", token),
  clear: () => localStorage.removeItem("aegis_token")
};

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original?._retry && tokenStore.get()) {
      original._retry = true;
      try {
        const { data } = await axios.post(`${API_URL}/auth/refresh`, null, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
        const token = data.access_token || data.token || data.jwt_token;
        if (token) {
          tokenStore.set(token);
          original.headers.Authorization = `Bearer ${token}`;
          return api(original);
        }
      } catch {
        tokenStore.clear();
        window.location.assign("/login");
      }
    }
    if (error.response?.status === 403) {
      window.dispatchEvent(new CustomEvent("aegis-toast", { detail: { type: "error", message: "You do not have permission for that action." } }));
    }
    return Promise.reject(error);
  }
);

export default api;
