// Chat enhancement functions - to be integrated into index.html

// Enhanced message rendering with reactions, edit indicators, and action buttons
function renderChatMessage(msg, isMe, myUsername) {
    const messagesDiv = document.getElementById('chat-messages');
    const time = msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
    const editedLabel = msg.edited_at ? ' <span style="font-size:0.7em; opacity:0.7;">(edited)</span>' : '';
    
    // Build reactions display
    let reactionsHtml = '';
    if (msg.reactions && Object.keys(msg.reactions).length > 0) {
        reactionsHtml = '<div style="display:flex; gap:4px; flex-wrap:wrap; margin-top:6px;">';
        for (const [emoji, users] of Object.entries(msg.reactions)) {
            const hasReacted = users.some(u => u.username === myUsername);
            const userList = users.map(u => u.username).join(', ');
            reactionsHtml += `<button onclick="toggleReaction(${msg.id}, '${emoji}')" title="${userList}" style="padding:3px 8px; border-radius:12px; border:1px solid ${hasReacted ? '#667eea' : 'var(--input-border)'}; background:${hasReacted ? '#e8f4fd' : 'var(--card-bg)'}; color:var(--text-primary); cursor:pointer; font-size:0.85em; display:flex; align-items:center; gap:4px;"><span>${emoji}</span><span style="font-size:0.8em;">${users.length}</span></button>`;
        }
        reactionsHtml += `<button onclick="openEmojiPickerForMessage(${msg.id})" style="padding:3px 8px; border-radius:12px; border:1px solid var(--input-border); background:var(--card-bg); color:var(--text-secondary); cursor:pointer; font-size:0.85em;">+</button>`;
        reactionsHtml += '</div>';
    } else {
        reactionsHtml = `<div style="margin-top:6px;"><button onclick="openEmojiPickerForMessage(${msg.id})" style="padding:3px 8px; border-radius:12px; border:1px solid var(--input-border); background:var(--card-bg); color:var(--text-secondary); cursor:pointer; font-size:0.75em; opacity:0.6;">Add reaction</button></div>`;
    }
    
    const escapedMessage = msg.message.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
    const bubble = document.createElement('div');
    bubble.id = `msg-${msg.id}`;
    bubble.style.cssText = `display:flex; flex-direction:column; align-items:${isMe?'flex-end':'flex-start'}; gap:2px; position:relative; padding:4px 0;`;
    bubble.innerHTML = `
        <span style="font-size:0.75em; color:var(--text-secondary);">${isMe ? 'You' : msg.sender} · ${time}</span>
        <div class="chat-message-wrapper" style="position:relative; max-width:75%;" onmouseenter="showMessageActions(${msg.id}, ${isMe})" onmouseleave="hideMessageActions(${msg.id})">
            <div style="padding:10px 14px; border-radius:${isMe?'16px 16px 4px 16px':'16px 16px 16px 4px'};
                 background:${isMe?'linear-gradient(135deg,#667eea,#764ba2)':'var(--list-hover)'};
                 color:${isMe?'white':'var(--text-primary)'}; word-break:break-word; font-size:0.95em; position:relative;">
                ${msg.message.replace(/</g,'&lt;').replace(/>/g,'&gt;')}${editedLabel}
            </div>
            ${isMe ? `<div id="msg-actions-${msg.id}" class="message-actions" style="display:none; position:absolute; top:-8px; right:-8px; background:var(--card-bg); border:1px solid var(--input-border); border-radius:8px; padding:2px; box-shadow:0 2px 8px rgba(0,0,0,0.15); z-index:10;">
                <button onclick="editChatMessage(${msg.id}, \`${escapedMessage}\`)" title="Edit" style="padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;">✏️</button>
                <button onclick="deleteChatMessage(${msg.id})" title="Delete" style="padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;">🗑️</button>
            </div>` : ''}
            ${reactionsHtml}
        </div>`;
    messagesDiv.appendChild(bubble);
}

function showMessageActions(messageId, isMe) {
    if (!isMe) return;
    const actions = document.getElementById(`msg-actions-${messageId}`);
    if (actions) actions.style.display = 'flex';
}

function hideMessageActions(messageId) {
    const actions = document.getElementById(`msg-actions-${messageId}`);
    if (actions) actions.style.display = 'none';
}

function openEmojiPicker() {
    const modal = document.getElementById('emoji-picker-modal');
    if (!modal) return;
    initEmojiGrid();
    emojiPickerCallback = (emoji) => {
        const input = document.getElementById('chat-input');
        input.value += emoji;
        input.focus();
    };
    modal.style.display = 'flex';
}

function openEmojiPickerForMessage(messageId) {
    const modal = document.getElementById('emoji-picker-modal');
    if (!modal) return;
    initEmojiGrid();
    emojiPickerCallback = (emoji) => {
        addReaction(messageId, emoji);
    };
    modal.style.display = 'flex';
}

function closeEmojiPicker() {
    const modal = document.getElementById('emoji-picker-modal');
    if (modal) modal.style.display = 'none';
    emojiPickerCallback = null;
}

function initEmojiGrid() {
    const grid = document.getElementById('emoji-grid');
    if (!grid || grid.children.length > 0) return;
    commonEmojis.forEach(emoji => {
        const btn = document.createElement('button');
        btn.textContent = emoji;
        btn.style.cssText = 'padding:8px; border:1px solid var(--input-border); border-radius:6px; background:var(--card-bg); cursor:pointer; font-size:1.5em; transition:all 0.2s;';
        btn.onmouseover = () => btn.style.transform = 'scale(1.2)';
        btn.onmouseout = () => btn.style.transform = 'scale(1)';
        btn.onclick = () => {
            if (emojiPickerCallback) emojiPickerCallback(emoji);
            closeEmojiPicker();
        };
        grid.appendChild(btn);
    });
}

async function addReaction(messageId, emoji) {
    try {
        const resp = await fetch(`/api/chat/message/${messageId}/react`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({emoji})
        });
        if (resp.ok) {
            await loadChatMessages(true);
        } else {
            const data = await resp.json();
            showMessage(data.error || 'Failed to add reaction', 'error');
        }
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function toggleReaction(messageId, emoji) {
    try {
        // Remove the reaction (user can re-add if needed)
        const resp = await fetch(`/api/chat/message/${messageId}/react?emoji=${encodeURIComponent(emoji)}`, {
            method: 'DELETE'
        });
        if (resp.ok) {
            await loadChatMessages(true);
        } else {
            const data = await resp.json();
            showMessage(data.error || 'Failed to toggle reaction', 'error');
        }
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function editChatMessage(messageId, currentText) {
    editingMessageId = messageId;
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const cancelBtn = document.getElementById('chat-cancel-edit-btn');
    
    input.value = currentText;
    input.focus();
    sendBtn.textContent = 'Save';
    cancelBtn.style.display = 'block';
}

async function cancelEditMessage() {
    editingMessageId = null;
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const cancelBtn = document.getElementById('chat-cancel-edit-btn');
    
    input.value = '';
    sendBtn.textContent = 'Send';
    cancelBtn.style.display = 'none';
}

async function deleteChatMessage(messageId) {
    if (!confirm('Delete this message?')) return;
    try {
        const resp = await fetch(`/api/chat/message/${messageId}`, {
            method: 'DELETE'
        });
        if (resp.ok) {
            showMessage('Message deleted', 'success');
            await loadChatMessages(false);
        } else {
            const data = await resp.json();
            showMessage(data.error || 'Failed to delete', 'error');
        }
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}
