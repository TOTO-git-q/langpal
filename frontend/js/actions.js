(function (global) {
  'use strict';
  const LP = global.LP = global.LP || {};

  async function request(path, body) {
    const response = await fetch('/api/workspace-agent/' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  // 管家的改动生效后，让各页面重读。课程管家页（workspace-agent.js）也用这一份
  async function refreshApp(result) {
    const tools = result.tools || [];
    if (result.browser) {
      const { key, value } = result.browser;
      if (!['reviewKind', 'reviewLanguage'].includes(key) || !LP.preferences?.set(key, value)) throw new Error('这一项没存上');
      LP.review?.setFilter(LP.preferences.get('reviewKind'), LP.preferences.get('reviewLanguage'));
    }
    if (tools.some(tool => tool.startsWith('reading.'))) global.dispatchEvent(new Event('lp:reading-settings'));
    if (tools.includes('language.add')) await LP.languages?.reload().catch(() => {});
    if (tools.some(tool => ['persona.edit', 'world.save', 'course.set'].includes(tool))) {
      await LP.appShell?.reloadPersonas().catch(() => {});
      document.dispatchEvent(new Event('lp:teaching-settings'));
    }
    if (tools.includes('coach.preferences')) {
      global.dispatchEvent(new Event('lp:coach-settings'));
      if (!LP.coach?.serviceChanged()) LP.coach?.refresh();
    }
    if (tools.some(tool => ['voice.listening', 'listening.plan'].includes(tool))) global.dispatchEvent(new Event('lp:listening-settings'));
  }

  async function switchPage(tab) {
    if (!Object.hasOwn(LP.scene.titles, tab)) throw new Error(String(tab));
    await LP.appShell.switchTab(tab, { waitForLeave: true });
    if (!document.getElementById('page-' + tab)?.classList.contains('active')) throw new Error(tab);
    await LP.appShell.ready(tab);
  }

  async function run(name, arg) {
    let label = '';
    try {
      switch (name) {
        case 'open':
          label = '▶ ' + (arg === 'course' ? '课程' : (LP.scene.titles[arg] || arg));
          if (arg === 'course') {
            await LP.appShell.need?.('teach');
            await LP.settingsTeaching.setLanguage(LP.state.chatMain?.language);
            await LP.settings.open('library');
          } else await switchPage(arg);
          break;
        case 'lesson':
          label = '▶ 上课';
          await LP.lesson.start(LP.state.chatMain?.language);
          break;
        case 'listen': {
          label = '▶ 听力';
          await switchPage('listening');
          const result = await LP.listening.start({ format: arg });
          if (result?.label && arg) label += ' · ' + result.label;
          if (!result?.ok) throw new Error(name);
          break;
        }
        case 'review': {
          label = '▶ 复习';
          await switchPage('drill');
          const start = document.querySelector('#page-drill [data-start-review], #page-drill [data-review-start]');
          if (start && !start.disabled && !start.hidden) start.click();
          break;
        }
        case 'language':
          label = '→ ' + (LP.state.chatMain?.languages?.find(item => item.tag === arg)?.label || LP.languages.label(arg));
          await LP.api.putMainChat({ language: arg });
          await LP.jine.refreshMain();
          break;
        case 'fun':
          label = arg === 'on' ? '骰子开' : '骰子关';
          await LP.api.putMainChat({ fun: arg === 'on' });
          await LP.jine.refreshMain();
          break;
        case 'voice':
          label = arg === 'on' ? '声音开' : '声音关';
          localStorage.setItem('lp.stage.voice', arg === 'on' ? '1' : '0');
          if (arg === 'off') LP.stage.stopSpeech();
          break;
        case 'save': {
          label = '＋ ' + arg;
          const language = LP.scene.get().language || LP.state.chatMain?.language;
          if (!language) throw new Error(name);
          await LP.api.addVocab({ language, lemma: arg, surface: arg, context_sentence: '' });
          break;
        }
        case 'manage': {
          // 只报结果和改了什么，不把指令原文、管家的回话当弹幕
          label = '课程管家';
          const plan = await request('plan', { message: arg });
          if (!plan.proposal) throw new Error(name);
          label = '✓ ' + String(plan.proposal.changes[0]?.label || '课程管家').slice(0, 40);
          const result = await request('apply', { id: plan.proposal.id });
          await refreshApp(result);
          break;
        }
        default: throw new Error(String(name));
      }
      return { ok: true, label };
    } catch (error) {
      return { ok: false, label: '× ' + label.replace(/^[▶→♪＋✓…]\s*/, '') };
    }
  }
  LP.actions = { run, refreshApp };
})(window);
