import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="not-found">
      <div className="not-found-code">404</div>
      <div className="not-found-title">找不到這個頁面</div>
      <p className="not-found-sub">你造訪的頁面不存在或已被移除。</p>
      <Link to="/" className="btn btn-primary">
        回到首頁
      </Link>
    </div>
  );
}