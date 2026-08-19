import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="not-found">
      <div className="not-found-code">404</div>
      <div className="not-found-title">{t("notFound.title")}</div>
      <p className="not-found-sub">{t("notFound.sub")}</p>
      <Link to="/" className="btn btn-primary">
        {t("common.backHome")}
      </Link>
    </div>
  );
}