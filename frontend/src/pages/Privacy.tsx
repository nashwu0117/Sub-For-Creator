import { useTranslation, Trans } from "react-i18next";

export default function Privacy() {
  const { t } = useTranslation();
  return (
    <article className="static-page">
      <h1>{t("privacy.title")}</h1>
      <p className="effective-date">{t("privacy.effective")}</p>

      <h2>{t("privacy.h1")}</h2>
      <ul>
        <li>
          <Trans
            i18nKey="privacy.uploaded"
            components={[<strong key="a" />, <strong key="b" />]}
          />
        </li>
        <li>
          <Trans
            i18nKey="privacy.subtitles"
            components={[<strong key="a" />]}
          />
        </li>
        <li>
          <Trans
            i18nKey="privacy.session"
            components={[<strong key="a" />, <strong key="b" />]}
          />
        </li>
      </ul>

      <h2>{t("privacy.h2")}</h2>
      <ul>
        <li>
          <Trans
            i18nKey="privacy.noTraining"
            components={[<strong key="a" />]}
          />
        </li>
        <li>
          <Trans
            i18nKey="privacy.noSelling"
            components={[<strong key="a" />]}
          />
        </li>
        <li>
          <Trans
            i18nKey="privacy.noAccount"
            components={[<strong key="a" />]}
          />
        </li>
      </ul>

      <h2>{t("privacy.h3")}</h2>
      <p>{t("privacy.responsibility")}</p>

      <h2>{t("privacy.h4")}</h2>
      <p>{t("privacy.contact")}</p>
    </article>
  );
}