/* ═══════════════════════════════════════════════════════════════════════════
   FORTISSIMO — ALGORITMO DI ANALISI (versione pura, senza interfaccia)
   ═══════════════════════════════════════════════════════════════════════════

   Cosa fa: dato un brano audio, (1) stima in quante sorgenti/strumenti è
   composto, (2) le separa, (3) trascrive le note di ciascuna sorgente (MIDI),
   (4) estrae un campione one-shot per sorgente, (5) ricostruisce il mix dal
   MIDI+campioni per misurarne la bontà (SI-SDR / MSE / correlazione).

   Pipeline (stessi nomi/passi dell'originale):
     FASE 1  specgram()   → spettrogramma FFT (N=2048, hop=512, finestra Hann)
     FASE 2  autoK()      → K-means su 16 bande spettrali + silhouette → n. sorgenti
     FASE 3  wiener()     → maschera di Wiener soft → separa i K segnali
     FASE 4  classify()   → features() → nome/tipo di ogni sorgente
     FASE 5  transcribe() → YIN + spectral flux → note (pitch/tempo/velocity)
     FASE 6  extract()    → campione one-shot (1,2 s) per sorgente
     FASE 7  recon()      → ricostruzione ADSR; siSdr()/mse()/corr() per la metrica

   PROVENIENZA: le funzioni qui sotto sono copiate **identiche** da
   `midi_studio/extractor.html` (a sua volta copia corretta di
   `fortissimo_pro.html`). L'unica differenza è che i richiami all'interfaccia
   (`log`, `sp`, `sl`) ora passano da callback opzionali: l'algoritmo non tocca
   il DOM e può girare in qualsiasi contesto (browser, worker, Node).

   USO (browser o Node, ES2017+):

     const audio = new Float32Array(...);          // mono, valori in [-1,1]
     const esito = await analizza(audio, {
        sr: 44100,          // sample rate
        maxK: 6,            // numero massimo di sorgenti da provare
        onsetSigma: 1.5,    // soglia onset per percussioni (deviazioni standard)
        minNoteMs: 50,      // durata minima di una nota
        onLog: m => console.log(m),
        onProgress: (fase, pct) => console.log(pct + '% ' + fase),
     });
     // esito.sources        → [{id,name,type,energyPct,features}, ...]
     // esito.notes          → { s0: [{pitch,start,end,velocity}, ...], ... }
     // esito.samples        → { s0: Float32Array(one-shot), ... }
     // esito.reconstructed  → Float32Array (mix ricostruito da MIDI+campioni)
     // esito.siSdr / .mse / .corr / .ms / .durationSec
     // writeMidi(nome, note) / writeMultiMidi(sources, notes) / writeWav(samples, sr)

   ═══════════════════════════════════════════════════════════════════════════ */

// ── Stato condiviso: gli stessi nomi globali dell'originale, così le funzioni
//    copiate funzionano senza modifiche.
let Sr = 44100;
let O = null;      // audio originale
let D = null;      // audio di lavoro (mono)
let R = null;      // ricostruzione
let SS = {};       // sorgenti separate: {id: Float32Array}
let DS = [];       // descrittori delle sorgenti: [{id,energy,rawEnergy,name,type,...}]
let TR = {};       // trascrizione: {id: [{pitch,start,end,velocity}]}
let SA = {};       // campioni one-shot: {id: Float32Array}
let SC = {};       // colori per il disegno (usati anche dall'UI)
const PL = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6", "#8b5cf6",
            "#ec4899", "#06b6d4", "#14b8a6", "#f59e0b"];

// Callback opzionali (sostituiscono le funzioni dell'interfaccia dell'originale)
let __onLog = null, __onProgress = null;
function log(m, t) { if (__onLog) { try { __onLog(m, t); } catch (e) {} } }
function sp(n, p) { if (__onProgress) { try { __onProgress(n, p); } catch (e) {} } }
function sl(ms) { return new Promise(r => setTimeout(r, ms)); }
function specgram(data,sr){
const N=2048,h=512,fr=Math.floor((data.length-N)/h),nb=N/2,spec=[];
for(let f=0;f<fr;f++){const frame=new Float32Array(N);const st=f*h;for(let i=0;i<N;i++)frame[i]=(data[st+i]||0)*(0.5-0.5*Math.cos(2*Math.PI*i/(N-1)));spec.push(fftMag(frame).slice(0,nb))}
const freqs=[];for(let k=0;k<nb;k++)freqs.push(k*sr/N);return{spec,freqs};
}
function fftMag(input){
const N=input.length,re=new Float32Array(N),im=new Float32Array(N);for(let i=0;i<N;i++)re[i]=input[i];
for(let len=2;len<=N;len<<=1){const half=len>>1;for(let i=0;i<N;i+=len){for(let j=0;j<half;j++){const a=-2*Math.PI*j/len;const c=Math.cos(a),s=Math.sin(a);const uR=re[i+j],uI=im[i+j];const vR=re[i+j+half]*c-im[i+j+half]*s;const vI=re[i+j+half]*s+im[i+j+half]*c;re[i+j]=uR+vR;im[i+j]=uI+vI;re[i+j+half]=uR-vR;im[i+j+half]=uI-vI}}}
const mag=new Float32Array(N/2);for(let k=0;k<N/2;k++)mag[k]=Math.sqrt(re[k]*re[k]+im[k]*im[k]);return mag;
}
function autoK(spec,maxK){
const nf=spec.length,nb=spec[0].length;
const feat=spec.map(f=>{const b=[];for(let i=0;i<16;i++){const s=Math.floor(nb*i/16),e=Math.floor(nb*(i+1)/16);let sum=0;for(let k=s;k<e;k++)sum+=f[k];b.push(sum/Math.max(1,e-s))}return b});
let bestK=2,bestSc=-Infinity;
for(let k=2;k<=Math.min(maxK,Math.floor(feat.length/8));k++){
const{labels,centroids}=kmeans(feat,k,30);const sc=silhouette(feat,labels,centroids,k);
log(' K='+k+' → sc='+sc.toFixed(3),'i');if(sc>bestSc){bestSc=sc;bestK=k}}
return bestK;
}
function kmeans(data,k,it){
const n=data.length,dim=data[0].length,cent=[];const used=new Set();
while(cent.length<k){const idx=Math.floor(Math.random()*n);if(!used.has(idx)){used.add(idx);cent.push([...data[idx]])}}
let lab=new Int32Array(n);
for(let iter=0;iter<it;iter++){
let chg=false;
for(let i=0;i<n;i++){let best=0,bd=Infinity;for(let c=0;c<k;c++){let d=0;for(let j=0;j<dim;j++)d+=(data[i][j]-cent[c][j])**2;if(d<bd){bd=d;best=c}}if(lab[i]!==best)chg=true;lab[i]=best}
if(!chg)break;
for(let c=0;c<k;c++){const sum=new Float32Array(dim);let cnt=0;for(let i=0;i<n;i++)if(lab[i]===c){for(let j=0;j<dim;j++)sum[j]+=data[i][j];cnt++}if(cnt>0)for(let j=0;j<dim;j++)cent[c][j]=sum[j]/cnt}}
return{labels:lab,centroids:cent};
}
function silhouette(data,labels,centroids,k){
const n=data.length,dim=data[0].length;let tot=0,cnt=0;
for(let i=0;i<n;i++){const ci=labels[i];let a=0,ac=0,b=Infinity;
for(let j=0;j<n;j++){if(i===j)continue;let d=0;for(let d2=0;d2<dim;d2++)d+=(data[i][d2]-data[j][d2])**2;d=Math.sqrt(d);if(labels[j]===ci){a+=d;ac++}}
for(let c=0;c<k;c++){if(c===ci)continue;let d=0;for(let j=0;j<dim;j++)d+=(data[i][j]-centroids[c][j])**2;b=Math.min(b,Math.sqrt(d))}
if(ac>0){a/=ac;tot+=(b-a)/Math.max(a,b);cnt++}}
return cnt>0?tot/cnt:0;
}
function wiener(spec,k,data){
const nf=spec.length,nb=spec[0].length;
const feat=spec.map(f=>{const b=[];for(let i=0;i<16;i++){const s=Math.floor(nb*i/16),e=Math.floor(nb*(i+1)/16);let sum=0;for(let k2=s;k2<e;k2++)sum+=f[k2];b.push(sum/Math.max(1,e-s))}return b});
const{labels,centroids}=kmeans(feat,k,40);
const cp=[];for(let c=0;c<k;c++){const p=new Float32Array(nb);let cnt=0;for(let f=0;f<nf;f++)if(labels[f]===c){for(let b=0;b<nb;b++)p[b]+=spec[f][b]*spec[f][b];cnt++}if(cnt>0)for(let b=0;b<nb;b++)p[b]/=cnt;cp.push(p)}
const masks=[];for(let f=0;f<nf;f++){const m=new Float32Array(k);let tot=0;for(let c=0;c<k;c++){let sim=0;for(let b=0;b<nb;b++)sim+=spec[f][b]*cp[c][b];m[c]=sim;tot+=sim}if(tot>0)for(let c=0;c<k;c++)m[c]/=tot;masks.push(m)}
const N=2048,h=512,srcs={};DS=[];
for(let c=0;c<k;c++){srcs['s'+c]=new Float32Array(data.length);SC['s'+c]=PL[c%PL.length]}
for(let f=0;f<nf;f++){const st=f*h;for(let c=0;c<k;c++){const w=masks[f][c];if(w<0.05)continue;for(let i=0;i<N&&st+i<data.length;i++){const win=0.5-0.5*Math.cos(2*Math.PI*i/(N-1));srcs['s'+c][st+i]+=data[st+i]*w*win*win}}}
const res={};for(let c=0;c<k;c++){const id='s'+c;const e=srcs[id].reduce((a,b)=>a+b*b,0);if(e>1e-8){res[id]=srcs[id];DS.push({id,energy:Math.sqrt(e/srcs[id].length),rawEnergy:e})}}
DS.sort((a,b)=>b.energy-a.energy);return res;
}
function classify(){
const te=DS.reduce((a,s)=>a+s.rawEnergy,0);
for(const s of DS){
const src=SS[s.id];const f=features(src,Sr);s.features=f;s.energyPct=(s.rawEnergy/te*100).toFixed(1);
if(f.centroid<200)s.name='Sub Bass';else if(f.centroid<400)s.name='Bass';else if(f.zcr>0.15&&f.centroid>3000)s.name='Hi-Hat';else if(f.zcr>0.08&&f.centroid>1500)s.name='Snare';else if(f.centroid<800&&f.zcr<0.05)s.name='Kick';else if(f.centroid>2500&&f.rolloff>6000)s.name='Synth/FX';else if(f.centroid>1500&&f.contrast>0.5)s.name='Brass';else if(f.centroid>800&&f.contrast<0.3)s.name='Pad/Strings';else if(f.centroid>500&&f.centroid<2000)s.name='Piano/Guitar';else s.name='Tonal';
s.type=f.centroid<500?'drums':(f.zcr>0.1?'perc':'tonal');
}
}
function features(data,sr){
const N=2048,h=512;let sc=0,sr2=0,sz=0,sct=0,cnt=0;
const freqs=[];for(let k=0;k<N/2;k++)freqs.push(k*sr/N);
for(let f=0;f<Math.floor((data.length-N)/h);f++){
const frame=data.slice(f*h,f*h+N);const mag=fftMag(frame);const tot=mag.reduce((a,b)=>a+b,0);if(tot<1)continue;
let c=0;for(let k=0;k<mag.length;k++)c+=freqs[k]*mag[k];c/=tot;
let r=0,cum=0;for(let k=0;k<mag.length;k++){cum+=mag[k];if(cum>tot*0.85){r=freqs[k];break}}
let z=0;for(let i=1;i<N;i++)if((frame[i]>=0)!==(frame[i-1]>=0))z++;z/=N;
let ct=0;for(let b=0;b<4;b++){const s=Math.floor(mag.length*b/4),e=Math.floor(mag.length*(b+1)/4);let p=0,v=Infinity;for(let k=s;k<e;k++){p=Math.max(p,mag[k]);v=Math.min(v,mag[k])}ct+=Math.log(p/(v+1e-10)+1)}ct/=4;
sc+=c;sr2+=r;sz+=z;sct+=ct;cnt++;
}
return{centroid:cnt?sc/cnt:0,rolloff:cnt?sr2/cnt:0,zcr:cnt?sz/cnt:0,contrast:cnt?sct/cnt:0};
}
function transcribe(data,sr,si,osig,mnd){
const type=si.type,notes=[];
if(type==='drums'||type==='perc'){
const h=512,N=1024,flux=[];
for(let f=1;f<Math.floor((data.length-N)/h);f++){let s=0;for(let i=0;i<N;i++){const d=Math.abs(data[f*h+i])-Math.abs(data[(f-1)*h+i]);if(d>0)s+=d}flux.push(s)}
const m=flux.reduce((a,b)=>a+b,0)/flux.length;const sd=Math.sqrt(flux.reduce((a,b)=>a+(b-m)**2,0)/flux.length);const th=m+osig*sd;
for(let i=0;i<flux.length;i++)if(flux[i]>th&&(i===0||flux[i]>flux[i-1])&&(i===flux.length-1||flux[i]>flux[i+1])){
const t=i*h/sr;const p=si.name.includes('Hi')?42:si.name.includes('Kick')?36:38;
notes.push({pitch:p,start:t,end:t+0.08,velocity:Math.min(127,Math.floor(50+(flux[i]-th)/sd*40))})}
}else{
const h=1024,N=2048;const mns=mnd/1000;let cn=null;
for(let f=0;f<Math.floor((data.length-N)/h);f++){
const frame=data.slice(f*h,f*h+N);const rms=Math.sqrt(frame.reduce((a,b)=>a+b*b,0)/N);if(rms<0.005){if(cn&&f*h/sr-cn.start>mns){cn.end=f*h/sr;notes.push(cn)}cn=null;continue}
const p=yin(frame,sr);const midi=p>0?Math.round(69+12*Math.log2(p/440)):0;const t=f*h/sr;
if(midi>=20&&midi<=120){if(cn&&Math.abs(cn.pitch-midi)<=1&&t-cn.start<2){cn.end=t+0.1;cn.velocity=Math.max(cn.velocity,Math.min(127,Math.floor(rms*400)))}else{if(cn&&t-cn.start>mns)notes.push(cn);cn={pitch:midi,start:t,end:t+0.1,velocity:Math.min(127,Math.floor(rms*400))}}}
else{if(cn&&t-cn.start>mns)notes.push(cn);cn=null}
}if(cn&&cn.end-cn.start>mns)notes.push(cn)
}return notes;
}
function yin(frame,sr){
const N=frame.length,diff=new Float32Array(N);
for(let tau=0;tau<N;tau++){let s=0;for(let j=0;j<N-tau;j++)s+=(frame[j]-frame[j+tau])**2;diff[tau]=s}
const cmndf=new Float32Array(N);cmndf[0]=1;let run=0;
for(let tau=1;tau<N;tau++){run+=diff[tau];cmndf[tau]=diff[tau]*tau/(run+1e-10)}
const minLag=Math.floor(sr/4000),maxLag=Math.min(N/2,Math.floor(sr/40));
let bt=0,bv=Infinity;
for(let tau=minLag;tau<maxLag;tau++)if(cmndf[tau]<0.1&&cmndf[tau]<bv){bv=cmndf[tau];bt=tau+0.5*(cmndf[tau-1]-cmndf[tau+1])/(cmndf[tau-1]-2*cmndf[tau]+cmndf[tau+1]+1e-10)}
return bt>0?sr/bt:0;
}
function extract(data,sr,si){
const tl=Math.min(Math.floor(sr*1.2),data.length);
if(si.type==='tonal'){
const h=1024,N=2048;const pitches=[];
for(let f=0;f<Math.floor((data.length-N)/h);f++){const p=yin(data.slice(f*h,f*h+N),sr);pitches.push({idx:f*h,pitch:p,midi:p>0?Math.round(69+12*Math.log2(p/440)):0})}
let bs=0,bl=0,bm=0,cs=0,cm=0;
for(let i=0;i<pitches.length;i++){if(pitches[i].midi===0){cs=i+1;continue}if(cm===0||Math.abs(pitches[i].midi-cm)>1){if(i-cs>bl){bl=i-cs;bs=pitches[cs].idx;bm=cm}cs=i;cm=pitches[i].midi}}
if(bl<3){let mr=0,mi=0;for(let i=0;i<data.length-tl;i+=Math.floor(sr*0.1)){let r=0;for(let j=0;j<tl;j++)r+=data[i+j]**2;r=Math.sqrt(r/tl);if(r>mr){mr=r;mi=i}}bs=mi}
return proc(data.slice(bs,bs+tl),sr);
}else{let mr=0,mi=0;for(let i=0;i<data.length-tl;i+=Math.floor(sr*0.05)){let r=0;for(let j=0;j<tl;j++)r+=data[i+j]**2;r=Math.sqrt(r/tl);if(r>mr){mr=r;mi=i}}return proc(data.slice(mi,mi+tl),sr)}
}
function proc(s,sr){
const f=new Float32Array(s.length);
for(let i=0;i<s.length;i++){let e=1;const fi=Math.floor(sr*0.01),fo=Math.floor(sr*0.05);if(i<fi)e=i/fi;if(i>s.length-fo)e=Math.min(e,(s.length-i)/fo);f[i]=s[i]*e}
let p=0;for(let i=0;i<f.length;i++){const av=Math.abs(f[i]);if(av>p)p=av;}if(p>0)for(let i=0;i<f.length;i++)f[i]/=p*1.2;return f;
}
function recon(trans,samples,targetLen,sr){
const recon=new Float32Array(targetLen);
for(const[id,notes]of Object.entries(trans)){const sample=samples[id];if(!sample||!notes)continue;
for(const note of notes){const st=Math.floor(note.start*sr);const ratio=Math.pow(2,(note.pitch-72)/12);const sl=Math.floor(sample.length/ratio);const nd=Math.floor((note.end-note.start)*sr);const al=Math.min(sl,nd);
for(let i=0;i<al&&st+i<targetLen;i++){const si=Math.floor(i*ratio);if(si<sample.length){let e=1;const a=Math.min(al*0.05,sr*0.01),rl=Math.min(al*0.2,sr*0.05);if(i<a)e=i/a;if(i>al-rl)e*=Math.min(e,(al-i)/rl);recon[st+i]+=sample[si]*(note.velocity/127)*e*0.6}}}}
let p=0;for(let i=0;i<recon.length;i++){const av=Math.abs(recon[i]);if(av>p)p=av;}if(p>0)for(let i=0;i<recon.length;i++)recon[i]/=p*1.1;return recon;
}
function siSdr(ref,est){const n=Math.min(ref.length,est.length);let rM=0,eM=0;for(let i=0;i<n;i++){rM+=ref[i];eM+=est[i]}rM/=n;eM/=n;let num=0,rR=0;for(let i=0;i<n;i++){const r=ref[i]-rM,e=est[i]-eM;num+=r*e;rR+=r*r}const a=num/(rR+1e-10);let p2=0,no=0;for(let i=0;i<n;i++){const r=ref[i]-rM,e=est[i]-eM;const p=a*r;p2+=p*p;no+=(e-p)*(e-p)}return 10*Math.log10(p2/(no+1e-10))}
function mse(ref,est){let s=0;for(let i=0;i<Math.min(ref.length,est.length);i++)s+=(ref[i]-est[i])**2;return s/Math.min(ref.length,est.length)}
function corr(ref,est){const n=Math.min(ref.length,est.length);let rM=0,eM=0;for(let i=0;i<n;i++){rM+=ref[i];eM+=est[i]}rM/=n;eM/=n;let num=0,d1=0,d2=0;for(let i=0;i<n;i++){const a=ref[i]-rM,b=est[i]-eM;num+=a*b;d1+=a*a;d2+=b*b}return num/(Math.sqrt(d1)*Math.sqrt(d2)+1e-10)}
function writeMidi(name,notes){
const b=[];const pb=x=>b.push(x&0xFF);const ps=s=>{for(let i=0;i<s.length;i++)pb(s.charCodeAt(i))};const p16=v=>{pb(v>>8);pb(v&0xFF)};const p32=v=>{pb(v>>24);pb(v>>16);pb(v>>8);pb(v&0xFF)};const vl=v=>{v=Math.max(0,Math.round(v)||0);if(v===0){pb(0);return}const buf=[];let t=v;while(t>0){buf.unshift(t&0x7F);t>>=7}for(let i=0;i<buf.length-1;i++)buf[i]|=0x80;for(const x of buf)pb(x)};
ps('MThd');p32(6);p16(1);p16(2);p16(480);ps('MTrk');const t0=b.length;p32(0);vl(0);pb(0xFF);pb(0x51);pb(3);pb(7);pb(0xA1);pb(0x20);vl(0);pb(0xFF);pb(0x2F);pb(0);p32at(t0,b.length-t0-4);
ps('MTrk');const t1=b.length;p32(0);vl(0);pb(0xFF);pb(0x03);pb(name.length);ps(name);const sorted=notes.slice().sort((a,b)=>a.start-b.start);let lt=0;sorted.forEach(n=>{const ton=Math.floor(n.start*2*480),tof=Math.floor(n.end*2*480);vl(ton-lt);pb(0x90);pb(n.pitch);pb(n.velocity);vl(tof-ton);pb(0x80);pb(n.pitch);pb(0);lt=tof});vl(0);pb(0xFF);pb(0x2F);pb(0);p32at(t1,b.length-t1-4);return new Uint8Array(b);
function p32at(off,v){b[off]=(v>>24)&0xFF;b[off+1]=(v>>16)&0xFF;b[off+2]=(v>>8)&0xFF;b[off+3]=v&0xFF}
}
function writeMultiMidi(srcs,trans){
const b=[];const pb=x=>b.push(x&0xFF);const ps=s=>{for(let i=0;i<s.length;i++)pb(s.charCodeAt(i))};const p16=v=>{pb(v>>8);pb(v&0xFF)};const p32=v=>{pb(v>>24);pb(v>>16);pb(v>>8);pb(v&0xFF)};const vl=v=>{v=Math.max(0,Math.round(v)||0);if(v===0){pb(0);return}const buf=[];let t=v;while(t>0){buf.unshift(t&0x7F);t>>=7}for(let i=0;i<buf.length-1;i++)buf[i]|=0x80;for(const x of buf)pb(x)};const p32a=(off,v)=>{b[off]=(v>>24)&0xFF;b[off+1]=(v>>16)&0xFF;b[off+2]=(v>>8)&0xFF;b[off+3]=v&0xFF};
const nt=srcs.length+1;ps('MThd');p32(6);p16(1);p16(nt);p16(480);ps('MTrk');const t0=b.length;p32(0);vl(0);pb(0xFF);pb(0x51);pb(3);pb(7);pb(0xA1);pb(0x20);vl(0);pb(0xFF);pb(0x2F);pb(0);p32a(t0,b.length-t0-4);
srcs.forEach(s=>{const notes=trans[s.id]||[];ps('MTrk');const t=b.length;p32(0);vl(0);pb(0xFF);pb(0x03);pb(s.id.length);ps(s.id);const sorted=notes.slice().sort((a,b)=>a.start-b.start);let lt=0;sorted.forEach(n=>{const ton=Math.floor(n.start*2*480),tof=Math.floor(n.end*2*480);vl(ton-lt);pb(0x90);pb(n.pitch);pb(n.velocity);vl(tof-ton);pb(0x80);pb(n.pitch);pb(0);lt=tof});vl(0);pb(0xFF);pb(0x2F);pb(0);p32a(t,b.length-t-4)});return new Uint8Array(b);
}
function writeWav(data,sr){
const n=data.length,buf=new ArrayBuffer(44+n*2),v=new DataView(buf);
const ws=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i))};const w32=(o,x)=>v.setUint32(o,x,true);const w16=(o,x)=>v.setUint16(o,x,true);
ws(0,'RIFF');w32(4,36+n*2);ws(8,'WAVE');ws(12,'fmt ');w32(16,16);w16(20,1);w16(22,1);w32(24,sr);w32(28,sr*2);w16(32,2);w16(34,16);ws(36,'data');w32(40,n*2);
for(let i=0;i<n;i++){const s=Math.max(-1,Math.min(1,data[i]));v.setInt16(44+i*2,s<0?s*0x8000:s*0x7FFF,true)}return new Uint8Array(buf);
}

// ═══════════════════════════════════════════════════════════════════════════
// INGRESSO UNICO: analizza() — stessa sequenza del run() dell'interfaccia,
// senza DOM. Restituisce un riepilogo con sorgenti, note, campioni e metriche.
// ═══════════════════════════════════════════════════════════════════════════
async function analizza(audio, opts) {
  opts = Object.assign({ sr: 44100, maxK: 6, onsetSigma: 1.5, minNoteMs: 50,
                         onLog: null, onProgress: null }, opts || {});
  __onLog = opts.onLog; __onProgress = opts.onProgress;

  Sr = opts.sr; O = audio; D = audio;
  SS = {}; DS = []; TR = {}; SA = {}; SC = {}; R = null;
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  const t0 = now();

  sp("FASE 1: Spettrogramma FFT", 8);
  const g = specgram(D, Sr);
  log("FFT 2048: " + g.spec.length + " frame", "i");

  sp("FASE 2: Rilevamento K sorgenti", 20);
  const nk = autoK(g.spec, opts.maxK);
  log("Rilevati " + nk + " strumenti", "g");

  sp("FASE 3: Separazione Wiener", 38);
  SS = wiener(g.spec, nk, D);
  log("Separati " + Object.keys(SS).length, "i");

  sp("FASE 4: Feature + Classificazione", 50);
  classify();

  sp("FASE 5: YIN + Spectral Flux", 65);
  TR = {}; let noteTotali = 0;
  for (const [id, src] of Object.entries(SS)) {
    const si = DS.find(s => s.id === id);
    const n = transcribe(src, Sr, si, opts.onsetSigma, opts.minNoteMs);
    TR[id] = n; noteTotali += n.length;
  }
  log("Note: " + noteTotali, "g");

  sp("FASE 6: Estrazione campioni", 78);
  SA = {};
  for (const [id, src] of Object.entries(SS)) {
    const si = DS.find(s => s.id === id);
    const s = extract(src, Sr, si);
    if (s) SA[id] = s;
  }
  log("Campioni: " + Object.keys(SA).length, "i");

  sp("FASE 7a: Ricostruzione ADSR", 88);
  R = recon(TR, SA, D.length, Sr);

  sp("FASE 7b: Metriche", 92);
  const sdr = siSdr(O, R), errore = mse(O, R), correlazione = corr(O, R);

  sp("Completato!", 100);
  log("SI-SDR: " + sdr.toFixed(1) + "dB | " + ((now() - t0) / 1000).toFixed(1) + "s", "g");

  return {
    sources: DS.map(s => ({ id: s.id, name: s.name, type: s.type,
                            energyPct: s.energyPct, features: s.features })),
    nSources: DS.length, nk,
    notes: TR, noteCount: noteTotali,
    samples: SA, reconstructed: R,
    siSdr: sdr, mse: errore, corr: correlazione,
    ms: now() - t0, durationSec: D.length / Sr, sr: Sr,
    state: { SS, DS, TR, SA, R },   // per usi avanzati
  };
}

/**
 * Rende il MIDI di UNA sorgente applicandolo al SUO campione one-shot.
 * È la stessa logica di recon() (trasposizione sul pitch + ADSR + velocity)
 * applicata a una sola traccia: così il MIDI "suona con lo strumento giusto",
 * perché il timbro viene dal one-shot estratto da quella sorgente.
 * @param {string} id       id della sorgente (es. "s0")
 * @param {object} esito    risultato di analizza()
 * @param {number} [durata] quanti campioni rendere (default: durata dell'audio)
 * @returns {Float32Array}  audio reso (vuoto se la sorgente non ha campione/note)
 */
function rendiTraccia(id, esito, durata) {
  const sr = esito.sr || Sr || 44100;
  const note = (esito.notes || {})[id] || [];
  const campione = (esito.samples || {})[id];
  if (!campione || !campione.length) return new Float32Array(0);
  const n = Math.max(1, Math.floor(durata || Math.round((esito.durationSec || 0) * sr) || campione.length));
  const t = {}, s = {};
  t[id] = note; s[id] = campione;
  return recon(t, s, n, sr);
}

/**
 * Mix di più tracce rese con rendiTraccia() (per "suona tutte insieme"):
 * è il mix composto con i one-shot scelti, non la somma delle tracce separate.
 * @param {string[]} [ids]  sorgenti da includere (default: tutte quelle con note)
 */
function rendiMix(ids, esito, durata) {
  const sr = esito.sr || Sr || 44100;
  const n = Math.max(1, Math.floor(durata || Math.round((esito.durationSec || 0) * sr)));
  const out = new Float32Array(n);
  (ids || Object.keys(esito.notes || {})).forEach(id => {
    const r = rendiTraccia(id, esito, n);
    for (let i = 0; i < n && i < r.length; i++) out[i] += r[i];
  });
  let mx = 1e-9;
  for (let i = 0; i < n; i++) { const a = Math.abs(out[i]); if (a > mx) mx = a; }
  if (mx > 0) for (let i = 0; i < n; i++) out[i] = out[i] / mx * 0.9;
  return out;
}

// Export per Node (nel browser sono già funzioni globali)
if (typeof module !== "undefined" && module.exports) {
  module.exports = { analizza, rendiTraccia, rendiMix, writeMidi, writeMultiMidi, writeWav,
                     specgram, autoK, wiener, features, classify, transcribe,
                     yin, extract, recon };
}
