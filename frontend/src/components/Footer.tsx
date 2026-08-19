import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <span>Sub for Creator 以 AGPL-3.0 授權釋出，開源免費使用。</span>
        <span>
          <Link to="/privacy">隱私權政策</Link> · <Link to="/terms">服務條款</Link>
        </span>
      </div>
    </footer>
  );
}