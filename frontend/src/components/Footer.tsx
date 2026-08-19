import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export default function Footer() {
  const { t } = useTranslation();
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <span>{t("footer.license")}</span>
        <span>
          <Link to="/privacy">{t("footer.privacy")}</Link> · <Link to="/terms">{t("footer.terms")}</Link>
        </span>
      </div>
    </footer>
  );
}