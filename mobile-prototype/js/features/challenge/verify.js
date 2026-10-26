/**
 * 赛后种子校验（03 §1.4、08 §5.9）：SS.challengeVerify
 *   run(reveal) → Promise<{ status, digest }>
 *     status: "ok"（承诺与种子一致）| "fail"（不一致）| "unavailable"（非安全上下文或无 crypto.subtle）| "invalid"（承诺原文不是挑战格式）
 *   sha256Hex(text) → Promise<小写 hex>；available() → bool
 * 计算用浏览器 crypto.subtle.digest；判断（digestMatches / seedMatches）在 model.js 的纯函数里。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const M = () => SS.challengeModel;

  function available() {
    return window.isSecureContext !== false && !!(globalThis.crypto && globalThis.crypto.subtle);
  }

  async function sha256Hex(text) {
    const buf = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function run(reveal) {
    if (!available()) return { status: "unavailable", digest: null };
    const input = M().commitmentInputOf(reveal);
    if (!input || !reveal || !reveal.seed_commitment) return { status: "invalid", digest: null };
    const digest = await sha256Hex(input);
    const ok = M().digestMatches(digest, reveal.seed_commitment) && M().seedMatches(reveal);
    return { status: ok ? "ok" : "fail", digest };
  }

  SS.challengeVerify = { run, sha256Hex, available };
})();
