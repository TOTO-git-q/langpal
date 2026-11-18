(function (global) {
  'use strict';
  const toggle = (key,label) => `<label class="reading-pref-row"><span>${label}</span><input type="checkbox" data-preference="${key}" role="switch"></label>`;
  function wire(root) {
    const field = root?.querySelector('[data-reading-furigana]'); if(!field || field.dataset.wired)return;
    field.dataset.wired='true'; field.checked=global.LP.furigana?.enabled() || false;
    field.onchange=()=>global.LP.furigana?.setEnabled(field.checked);
    global.addEventListener('lp:furigana',event=>{field.checked=event.detail.enabled;});
  }
  (global.LP ||= {}).readingPreferences = {wire,get markup() {
    return `<div class="reading-preferences">
      <div class="reading-pref-heading"><h2>阅读习惯</h2></div>
      ${toggle('readerImages','文章封面')}${toggle('readerLookup','点词查义')}${toggle('readerPretranslate','先翻好句子')}
      <label class="reading-pref-row"><span>汉字注音 <ruby>日本語<rt>にほんご</rt></ruby></span><input type="checkbox" data-reading-furigana role="switch" aria-label="汉字注音"></label>
    </div>`;
  }};
})(window);
