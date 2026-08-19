import { useTranslation, Trans } from "react-i18next";

export default function Terms() {
  const { t } = useTranslation();
  return (
    <article className="static-page">
      <h1>{t("terms.title")}</h1>
      <p className="effective-date">{t("terms.effective")}</p>

      <h2>{t("terms.h1")}</h2>
      <p>{t("terms.s1")}</p>

      <h2>{t("terms.h2")}</h2>
      <p>{t("terms.s2intro")}</p>
      <ul>
        <li>{t("terms.s2a")}</li>
        <li>{t("terms.s2b")}</li>
        <li>{t("terms.s2c")}</li>
        <li>{t("terms.s2d")}</li>
      </ul>

      <h2>{t("terms.h3")}</h2>
      <p>{t("terms.s3")}</p>

      <h2>{t("terms.h4")}</h2>
      <p>{t("terms.s4")}</p>

      <h2>{t("terms.h5")}</h2>
      <ul>
        <li>
          <Trans i18nKey="terms.s5a" components={[<strong key="a" />]} />
        </li>
        <li>{t("terms.s5b")}</li>
        <li>{t("terms.s5c")}</li>
      </ul>

      <h2>{t("terms.h6")}</h2>
      <p>{t("terms.s6")}</p>

      <h2>{t("terms.h7")}</h2>
      <p>{t("terms.s7")}</p>

      <p style={{ marginTop: "2rem", fontSize: "13px", color: "var(--text-faint)" }}>
        {t("terms.note")}
      </p>
    </article>
  );
}