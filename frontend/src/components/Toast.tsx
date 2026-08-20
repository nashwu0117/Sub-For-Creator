import { useAuth } from "../context/AuthContext";

/** App 層級的 toast（登入/註冊/作品操作回饋），由 AuthContext 驅動 */
export default function Toast() {
  const { toast } = useAuth();
  if (!toast) return null;
  return (
    <div
      className={`toast${toast.kind === "error" ? " toast-error" : ""}`}
      role={toast.kind === "error" ? "alert" : "status"}
      aria-live={toast.kind === "error" ? "assertive" : "polite"}
      aria-atomic="true"
    >
      {toast.message}
    </div>
  );
}