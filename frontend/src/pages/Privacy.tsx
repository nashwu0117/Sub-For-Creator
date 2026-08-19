export default function Privacy() {
  return (
    <article className="static-page">
      <h1>隱私權政策</h1>
      <p className="effective-date">生效日期：2026-08-19</p>

      <h2>我們處理哪些資料</h2>
      <ul>
        <li>
          <strong>上傳的影片/音檔</strong>：僅用於產生字幕，處理完畢後保留 <strong>48 小時</strong>（可依設定調整），到期後自動永久刪除。
        </li>
        <li>
          <strong>字幕文字</strong>：儲存於伺服器資料庫，僅供你在作業有效期限內查看與編輯，作業到期後一併刪除。
        </li>
        <li>
          <strong>Session token</strong>：匿名識別碼（瀏覽器 localStorage 隨機產生），僅用於限流與作業歸屬，<strong>不包含任何個人資料</strong>。
        </li>
      </ul>

      <h2>我們不做什麼</h2>
      <ul>
        <li>
          <strong>不用你的資料訓練模型</strong>。所有語音辨識皆使用預訓練的開源 WhisperX 模型，你的影片不會進入任何訓練資料集。
        </li>
        <li>
          <strong>不販售、不分享、不出租</strong>你的影片或字幕給任何第三方。
        </li>
        <li>
          <strong>不提供帳號系統</strong>：v1 不收集姓名、Email 等個人資料。
        </li>
      </ul>

      <h2>內容責任</h2>
      <p>
        本服務為自動化工具。你必須擁有上傳內容的合法權利，且不得上傳違法、侵權、色情或違反服務條款的內容。違反者將被限制使用。
      </p>

      <h2>聯絡</h2>
      <p>如對本政策有疑問，請透過專案 GitHub repository 開 issue 聯繫維護者。</p>
    </article>
  );
}