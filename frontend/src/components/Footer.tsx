import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export default function Footer() {
  const { t } = useTranslation();
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <span className="footer-credit">
          <span>{t("footer.license")}</span>
          <span className="footer-developer" aria-label={t("footer.developer")}>
            © 2026 {t("footer.developer")}
          </span>
        </span>
        <span>
          <Link to="/privacy">{t("footer.privacy")}</Link> · <Link to="/terms">{t("footer.terms")}</Link>
        </span>
      </div>
    </footer>
  );
}