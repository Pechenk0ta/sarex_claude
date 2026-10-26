/** Minimal Telegram Bot API client. */

const TG_MAX_TEXT = 4000; // Telegram limit is 4096

function tg_(method, payload) {
  const token = botToken_();
  if (!token) throw new Error('Не задан токен бота (BOT_TOKEN_IN_CODE или свойство BOT_TOKEN)');
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload || {}),
    muteHttpExceptions: true,
  });
  const body = JSON.parse(resp.getContentText());
  if (!body.ok) throw new Error('Telegram ' + method + ': ' + body.description);
  return body.result;
}

function sendMessage_(chatId, text, replyMarkup) {
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
  };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  return tg_('sendMessage', payload);
}

/** Sends a long text as several messages, splitting on line breaks. */
function sendLong_(chatId, text) {
  let chunk = '';
  text.split('\n').forEach(function (line) {
    if (chunk && chunk.length + line.length + 1 > TG_MAX_TEXT) {
      sendMessage_(chatId, chunk);
      chunk = '';
    }
    chunk += (chunk ? '\n' : '') + line;
  });
  if (chunk) sendMessage_(chatId, chunk);
}

function editMessage_(chatId, messageId, text) {
  return tg_('editMessageText', {
    chat_id: chatId,
    message_id: messageId,
    text: text,
    parse_mode: 'HTML',
  });
}

/**
 * Stops the spinner on the pressed button. Best effort: Telegram accepts the answer only
 * for a few seconds and we poll once a minute, so "query is too old" is normal here.
 */
function answerCallback_(callbackId, text) {
  try {
    tg_('answerCallbackQuery', { callback_query_id: callbackId, text: text || '' });
  } catch (e) {
    console.warn(e);
  }
}

function esc_(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
