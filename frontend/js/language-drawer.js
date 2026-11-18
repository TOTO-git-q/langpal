/* Shared language registry drawer; all additions use the same /api/languages API. */
(() => {
  'use strict';
  let nextId = 0;
  const LP = window.LP;
  function create({title = '学习语言', selected = () => '', onSelect, onSource, onImport} = {}) {
    const dialog = document.createElement('dialog');
    const headingId = 'language-drawer-title-' + (++nextId);
    dialog.className = 'language-drawer jine-dialog';
    dialog.setAttribute('aria-labelledby', headingId);
    dialog.innerHTML = `<header><h2 id="${headingId}"></h2><button type="button" data-close aria-label="关闭语言抽屉">×</button></header>
      <section class="language-drawer-known"><h3>我的语言</h3><div data-languages="known"></div></section>
      <section class="language-drawer-add"><h3>添加其他语言</h3>
      <label class="jine-language-search"><input type="search" aria-label="搜索语言" placeholder="搜索，例如 Français" maxlength="60" autocomplete="off"></label>
      <p class="jine-dialog-note" role="status"></p>
      <ul class="jine-language-results" aria-label="可添加语言"></ul>
      <details class="jine-language-custom"><summary>自己填</summary><form>
        <label>显示名称<input name="label" maxlength="45" required placeholder="例如：巴西葡萄牙语"></label>
        <label>语言代码<input name="tag" maxlength="35" autocomplete="off" required placeholder="例如 pt-BR"></label>
        <button class="jine-primary" type="submit">添加语言</button></form></details></section>
      <footer><div data-languages="actions"></div></footer>`;
    dialog.querySelector('h2').textContent = title;
    document.body.append(dialog);
    const choose = tag => onSelect?.(tag);
    const opener = document.createElement('button');
    LP.languagePicker.mount(dialog, opener, choose);
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.addEventListener('click', event => { if(event.target===dialog) {
      const box=dialog.getBoundingClientRect();
      if(event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom) dialog.close();
    }});
    const known = dialog.querySelector('[data-languages="known"]');
    const renderKnown = () => {
      known.replaceChildren(...LP.languages.list().map(({tag,label}) => {
        const button=document.createElement('button');button.type='button';button.textContent=label;
        button.lang=tag;button.dataset.language=tag;button.setAttribute('aria-pressed', String(tag===selected()));
        button.onclick=()=>{choose(tag);dialog.close();};
        // 自带的三门和正在用的那门不能拿掉（拿掉正在用的，拨片上就一个都没选中了）
        if(['ja','en','de'].includes(tag)||tag===selected())return button;
        const row=document.createElement('span');
        const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','移除');
        remove.onclick=async()=>{
          if(!await LP.util.confirm({title:`拿掉「${label}」？`,ok:'拿掉'}))return;
          try{
            const response=await fetch('/api/languages/'+encodeURIComponent(tag),{method:'DELETE'});
            if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||'没拿掉，再试一次');
            await LP.languages.reload();renderKnown();
          }catch(error){LP.toast?.(LP.util.message(error,'没拿掉，再试一次'));}
        };
        row.append(button,remove);return row;
      }));
    };
    document.addEventListener('lp:languages',renderKnown);
    for(const [label, callback] of [['内容来源',onSource],['导入阅读材料',onImport]]) {
      if(!callback) continue;
      const button=document.createElement('button');button.type='button';button.textContent=label;
      button.onclick=()=>{dialog.close();callback();};dialog.querySelector('[data-languages="actions"]').append(button);
    }
    return {open(){renderKnown();opener.onclick();}, close(){dialog.close();}, element:dialog};
  }
  LP.languageDrawer={create};
})();
