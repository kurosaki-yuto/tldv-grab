// tl;dv 録画 抽出ブックマークレット (フリープラン可 / 公式API不要 / 外部サービス不使用)
//
// 録画ページ (https://tldv.io/app/meetings/<id>) で1回押すだけ。
// セッションはブラウザ内で完結。トークンはどこにも送信しない。
// 出てきた m3u8 をクリップボードから受け取り:
//   pbpaste > rec.m3u8 && tldv-grab hls rec.m3u8 out.mp4
javascript:(function(){
  var id=location.pathname.split('/').filter(Boolean).pop();
  if(!/^[a-f0-9]{24}$/i.test(id)){alert('録画ページで実行してください (URLが /app/meetings/<id> の形)');return;}

  // セッショントークンを localStorage / cookie から探す
  var tok=null;
  try{
    for(var i=0;i<localStorage.length;i++){
      var k=localStorage.key(i),v=localStorage.getItem(k);
      if(!v)continue;
      if(/^ey[A-Za-z0-9_-]{10,}\./.test(v)){tok=v;break;}
      try{var j=JSON.parse(v);var c=j&&(j.token||j.accessToken||j.access_token||j.jwt);
          if(typeof c==='string'&&/^ey[A-Za-z0-9_-]{10,}\./.test(c)){tok=c;break;}}catch(e){}
    }
  }catch(e){}
  if(!tok){var m=document.cookie.match(/(?:^|;\s*)tldvtoken=([^;]+)/);if(m)tok=decodeURIComponent(m[1]);}
  if(!tok){alert('セッショントークンが見つかりません。tl;dv にログインした状態で実行してください。');return;}

  fetch('https://gw.tldv.io/v1/meetings/'+id+'/watch-page?noTranscript=true',
        {headers:{Authorization:'Bearer '+tok,Accept:'application/json'}})
  .then(function(r){if(!r.ok)throw new Error('watch-page HTTP '+r.status);return r.json();})
  .then(function(j){
    // レスポンス中から m3u8 / media-files を再帰的に探す
    var hits=[];
    (function walk(o,p){
      if(!o||typeof o!=='object'||hits.length>20)return;
      Object.keys(o).forEach(function(k){
        var v=o[k];
        if(typeof v==='string'&&/\.m3u8|mpegurl|media-files\.tldv/i.test(v))hits.push({path:p+'.'+k,val:v});
        else if(v&&typeof v==='object')walk(v,p+'.'+k);
      });
    })(j,'');
    if(!hits.length){
      console.log('[tldv] watch-page response keys:',Object.keys(j));
      alert('プレイリストが見つかりませんでした。\nDevTools のコンソールにレスポンス構造を出したので、そちらを確認してください。');
      return;
    }
    var src=hits[0].val;
    var done=function(txt){
      var n=(txt.match(/^https?:\/\//gm)||[]).length;
      navigator.clipboard.writeText(txt).then(function(){
        alert('コピー完了\nセグメント '+n+'本 / '+txt.length+' bytes\n\nターミナルで:\n  pbpaste > rec.m3u8 && tldv-grab hls rec.m3u8');
      });
    };
    if(/^data:/.test(src)){done(atob(src.substring(src.indexOf(',')+1)));}
    else{fetch(src).then(function(r){return r.text();}).then(done);}
  })
  .catch(function(e){alert('失敗: '+e.message);});
})();
