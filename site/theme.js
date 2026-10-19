// 첫 그리기 전에 실행 (CSP 때문에 인라인 대신 별도 파일)
// 1) 기본은 흰색(라이트). 사용자가 다크를 고른 경우에만 다크.  2) JS가 동작할 때만 등장 모션용 숨김을 켠다.
(function () {
  var root = document.documentElement;
  try { if (localStorage.getItem("tw-theme") === "dark") root.setAttribute("data-theme", "dark"); } catch (e) { /* 저장소 차단 */ }
  if (!window.matchMedia || !window.matchMedia("(prefers-reduced-motion: reduce)").matches) root.classList.add("motion");
})();
