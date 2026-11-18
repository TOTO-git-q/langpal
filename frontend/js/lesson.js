(function (global) {
  'use strict';
  const {LP} = global;
  let lesson = null, revision = 0;
  // 后端没给中文说明的错（api.js 只能拼出「请求失败（状态码）」）：换成人话再往外抛
  const call = (promise) => promise.catch((error) => {
    if (/^请求失败/.test(error.message)) error.message = error.status === 409 ? '这节课已经结束了' : '没连上';
    throw error;
  });
  function store(value) {
    lesson = value;
    document.dispatchEvent(new CustomEvent('lp:lesson', {detail: lesson}));
    return lesson;
  }
  async function refresh() {
    const request = ++revision;
    const result = await call(LP.api.getLesson());
    return request === revision ? store(result.lesson || null) : lesson;
  }
  async function start(language, lessonId) {
    try {
      const result = await call(LP.api.startLesson({language, ...(lessonId ? {lesson_id: lessonId} : {})}));
      ++revision;
      const view = store(result.lesson || null);
      LP.appShell.switchTab('course');
      await LP.appShell.ready('course');
      return view;
    } catch (error) { LP.toast?.(error.message); throw error; }
  }
  // 再来一道：只上最后那张卡；写死的题用完了就当场出新的，所以可能要等一会儿。出错由按钮自己显示。
  async function more(language, lessonId) {
    const result = await call(LP.api.startLesson({language, lesson_id: lessonId, practice: true}));
    ++revision;
    return store(result.lesson || null);
  }
  // 限时写作的练习：在聊天页里写，她来批改
  async function write(language, lessonId) {
    const view = await more(language, lessonId);
    LP.appShell.switchTab('talk');
    return view;
  }
  async function answer(runId, card, item, text) {
    const result = await call(LP.api.answerLesson({run_id: runId, card, item, text}));
    ++revision;
    store(result.lesson || null);
    return result.check;
  }
  // 她接一句只在聊天页里写的限时写作之后；课程页上的课和练习交卷，聊天里不出声
  async function submit(runId, text, seconds) {
    const result = await call(LP.api.submitLesson({run_id: runId, text, seconds}));
    ++revision;
    const view = store(result.lesson || null);
    if (view?.venue === 'chat') void LP.jine.proactiveNow().catch(() => {});
    return view;
  }
  async function quiz(runId, answers, seconds) {
    const result = await call(LP.api.quizLesson({run_id: runId, answers, seconds}));
    ++revision;
    return store(result.lesson || null);
  }
  async function stop(view) {
    const result = await call(LP.api.stopLesson({run_id: view.id, dismiss: view.ended}));
    ++revision;
    return store(result.lesson || null);
  }
  async function practice(language, lessonId) {
    const view = await more(language, lessonId);
    LP.appShell.switchTab('course');
    await LP.appShell.ready('course');
    return view;
  }
  LP.lesson = {current: () => lesson, refresh, start, more, write, practice, answer, submit, quiz, stop};
})(window);
