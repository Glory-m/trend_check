// 첫 그리기 전에 실행 (CSP 때문에 인라인 대신 별도 파일)
// 1) 저장된 테마 적용 → 깜빡임 방지  2) JS가 동작할 때만 등장 모션용 숨김을 켠다 (JS 실패 시 내용이 숨지 않게)
(function () {
  var root = document.documentElement;
  try {
    var t = localStorage.getItem("tw-theme");
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t);
  } catch (e) { /* 저장소 차단 시 시스템 설정을 따른다 */ }
  if (!window.matchMedia || !window.matchMedia("(prefers-reduced-motion: reduce)").matches) root.classList.add("motion");
  root.classList.add("is-booting");
})();
