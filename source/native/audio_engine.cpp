#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <functiondiscoverykeys_devpkey.h>
#include <wrl/client.h>
#include <avrt.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
using Microsoft::WRL::ComPtr;
#define API extern "C" __declspec(dllexport)

struct ComScope {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    ~ComScope() { if (SUCCEEDED(hr)) CoUninitialize(); }
};
static void check(HRESULT hr) { if (FAILED(hr)) throw hr; }

// Bounded FIFO. WASAPI thread ONLY tries the lock: it never waits for Python,
// inference, GUI, disk, allocation, or a contended mutex.
struct Ring {
    std::mutex lock;
    std::vector<float> data;
    size_t begin = 0, count = 0;
    std::atomic<unsigned long long> drops{0}, starved{0};
    explicit Ring(size_t capacity) : data(capacity, 0.f) {}
    void push_locked(const float* x, size_t n) {
        for (size_t i=0; i<n; ++i) {
            if (count == data.size()) { begin = (begin+1)%data.size(); --count; ++drops; }
            data[(begin+count)%data.size()] = x[i]; ++count;
        }
    }
    size_t pop_locked(float* x, size_t n) {
        size_t take = std::min(n,count);
        for (size_t i=0; i<take; ++i) x[i]=data[(begin+i)%data.size()];
        begin=(begin+take)%data.size(); count-=take;
        return take;
    }
};

struct Stream {
    Ring ring{28800}; // bounded 600ms; supports calibrated blocks up to 400ms
    std::atomic<long> error{0};
    std::atomic<bool> muted{false};
    std::atomic<ULONGLONG> written{0};
    std::atomic<double> latency{0}, peak{0};
    std::atomic<unsigned long long> discontinuities{0};
    HANDLE stop = CreateEventW(nullptr,TRUE,FALSE,nullptr);
    std::thread worker;
    bool capture;
    Stream(bool input) : capture(input) {}
    ~Stream() { SetEvent(stop); if(worker.joinable()) worker.join(); CloseHandle(stop); }
    void run(std::wstring id, std::promise<HRESULT> ready) {
        bool reported=false;
        HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        HANDLE task=nullptr;
        ComScope com;
        ComPtr<IAudioClient> client;
        try {
            check(com.hr);
            ComPtr<IMMDeviceEnumerator> enumerator;
            check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)));
            ComPtr<IMMDevice> device;
            if(id.empty()) check(enumerator->GetDefaultAudioEndpoint(capture?eCapture:eRender,eCommunications,&device));
            else check(enumerator->GetDevice(id.c_str(),&device));
            check(device->Activate(__uuidof(IAudioClient),CLSCTX_ALL,nullptr,reinterpret_cast<void**>(client.GetAddressOf())));
            WAVEFORMATEX fmt{};
            fmt.wFormatTag=WAVE_FORMAT_IEEE_FLOAT;
            fmt.nChannels=2; fmt.nSamplesPerSec=48000; fmt.wBitsPerSample=32;
            fmt.nBlockAlign=8; fmt.nAvgBytesPerSec=48000*8;
            check(client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
                AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY | AUDCLNT_STREAMFLAGS_NOPERSIST,
                0,0,&fmt,nullptr));
            check(client->SetEventHandle(event));
            UINT32 capacity=0; check(client->GetBufferSize(&capacity));
            REFERENCE_TIME hns=0; check(client->GetStreamLatency(&hns)); latency=double(hns)/10000.;
            std::vector<float> mono(std::max<UINT32>(capacity,48000),0.f);
            ComPtr<IAudioCaptureClient> input;
            ComPtr<IAudioRenderClient> output;
            if(capture) check(client->GetService(IID_PPV_ARGS(&input)));
            else {
                check(client->GetService(IID_PPV_ARGS(&output)));
                BYTE* p=nullptr; check(output->GetBuffer(capacity,&p));
                check(output->ReleaseBuffer(capacity,AUDCLNT_BUFFERFLAGS_SILENT));
            }
            DWORD index=0; task=AvSetMmThreadCharacteristicsW(L"Audio",&index);
            check(client->Start()); ready.set_value(S_OK); reported=true;
            HANDLE events[]={stop,event};
            bool first_packet=true;
            while(true) {
                DWORD wait=WaitForMultipleObjects(2,events,FALSE,2000);
                if(wait==WAIT_OBJECT_0) break;
                if(wait!=WAIT_OBJECT_0+1) throw HRESULT(AUDCLNT_E_DEVICE_INVALIDATED);
                if(capture) {
                    UINT32 packet=0; check(input->GetNextPacketSize(&packet));
                    while(packet) {
                        BYTE* bytes=nullptr; UINT32 frames=0; DWORD flags=0;
                        check(input->GetBuffer(&bytes,&frames,&flags,nullptr,nullptr));
                        if(frames>mono.size()) { input->ReleaseBuffer(frames); throw HRESULT(E_UNEXPECTED); }
                        float level=0;
                        for(UINT32 i=0;i<frames;++i) {
                            auto x=reinterpret_cast<float*>(bytes);
                            float value=(flags&AUDCLNT_BUFFERFLAGS_SILENT)?0.f:(x[2*i]+x[2*i+1])*.5f;
                            mono[i]=std::isfinite(value)?value:0.f;
                            level=std::max(level,std::abs(mono[i]));
                        }
                        peak=level;
                        if(!first_packet && (flags&AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY)) ++discontinuities;
                        first_packet=false;
                        {
                            std::unique_lock guard(ring.lock,std::try_to_lock);
                            if(guard.owns_lock()) ring.push_locked(mono.data(),frames);
                            else ring.drops+=frames;
                        }
                        check(input->ReleaseBuffer(frames)); check(input->GetNextPacketSize(&packet));
                    }
                } else {
                    UINT32 padding=0; check(client->GetCurrentPadding(&padding));
                    UINT32 frames=capacity-padding; if(!frames) continue;
                    BYTE* bytes=nullptr; check(output->GetBuffer(frames,&bytes));
                    size_t take=0;
                    {
                        std::unique_lock guard(ring.lock,std::try_to_lock);
                        if(guard.owns_lock()) {
                            if(muted || GetTickCount64()-written.load()>800) { ring.count=0; ring.begin=0; }
                            else take=ring.pop_locked(mono.data(),frames);
                        }
                    }
                    if(take<frames) ring.starved+=frames-take;
                    float level=0;
                    auto x=reinterpret_cast<float*>(bytes);
                    for(UINT32 i=0;i<frames;++i) {
                        float v=i<take?std::clamp(mono[i],-1.f,1.f):0.f;
                        x[2*i]=v; x[2*i+1]=v; level=std::max(level,std::abs(v));
                    }
                    peak=level;
                    check(output->ReleaseBuffer(frames,take?0:AUDCLNT_BUFFERFLAGS_SILENT));
                }
            }
        } catch(HRESULT hr) { error=hr; if(!reported) { ready.set_value(hr); reported=true; } }
        catch(...) { error=E_FAIL; if(!reported) ready.set_value(E_FAIL); }
        if(client) client->Stop();
        if(task) AvRevertMmThreadCharacteristics(task);
        CloseHandle(event);
    }
};

API int vc_devices(wchar_t* result,int capacity) {
    ComScope com;
    try {
        // Qt may already have initialized the UI thread as STA. Enumeration
        // works in either apartment; only our owned stream threads need MTA.
        if(com.hr!=RPC_E_CHANGED_MODE) check(com.hr);
        ComPtr<IMMDeviceEnumerator> enumerator;
        check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)));
        std::wstring text;
        for(int flow=0;flow<2;++flow) {
            ComPtr<IMMDeviceCollection> devices;
            check(enumerator->EnumAudioEndpoints(flow==0?eCapture:eRender,DEVICE_STATE_ACTIVE,&devices));
            UINT count=0; devices->GetCount(&count);
            for(UINT i=0;i<count;++i) {
                ComPtr<IMMDevice> device; check(devices->Item(i,&device));
                LPWSTR id=nullptr; check(device->GetId(&id));
                std::wstring ident(id); CoTaskMemFree(id);
                ComPtr<IPropertyStore> properties; check(device->OpenPropertyStore(STGM_READ,&properties));
                PROPVARIANT value; PropVariantInit(&value);
                check(properties->GetValue(PKEY_Device_FriendlyName,&value));
                std::wstring name=value.vt==VT_LPWSTR?value.pwszVal:L"Audio device";
                PropVariantClear(&value);
                std::replace(name.begin(),name.end(),L'\t',L' ');
                std::replace(name.begin(),name.end(),L'\n',L' ');
                text+=(flow==0?L"capture\t":L"render\t")+ident+L"\t"+name+L"\n";
            }
        }
        if(capacity<=int(text.size())) return -int(text.size()+1);
        wcscpy_s(result,capacity,text.c_str()); return int(text.size());
    } catch(...) { return -1; }
}
API void* vc_open(int capture,const wchar_t* id,long* error) {
    try {
        auto stream=std::make_unique<Stream>(capture!=0);
        std::promise<HRESULT> promise; auto future=promise.get_future();
        stream->worker=std::thread(&Stream::run,stream.get(),id?id:L"",std::move(promise));
        auto hr=future.get(); *error=hr;
        if(FAILED(hr)) return nullptr;
        return stream.release();
    } catch(...) { *error=E_FAIL; return nullptr; }
}
API void vc_close(void* handle) { delete static_cast<Stream*>(handle); }
API int vc_read(void* handle,float* x,int n) {
    auto s=static_cast<Stream*>(handle);
    std::lock_guard guard(s->ring.lock);
    if(s->ring.count<size_t(n)) return 0;
    return int(s->ring.pop_locked(x,n));
}
API void vc_write(void* handle,const float* x,int n) {
    auto s=static_cast<Stream*>(handle);
    std::lock_guard guard(s->ring.lock);
    s->ring.push_locked(x,n); s->written=GetTickCount64();
}
API void vc_mute(void* handle,int muted) {
    auto s=static_cast<Stream*>(handle); s->muted=muted!=0;
    if(muted) { std::lock_guard guard(s->ring.lock); s->ring.count=0; s->ring.begin=0; }
}
API void vc_flush(void* handle) {
    auto s=static_cast<Stream*>(handle);
    std::lock_guard guard(s->ring.lock); s->ring.count=0; s->ring.begin=0;
}
API void vc_stats(void* handle,double* stats) {
    auto s=static_cast<Stream*>(handle);
    std::lock_guard guard(s->ring.lock);
    stats[0]=s->ring.count; stats[1]=double(s->ring.drops.load());
    stats[2]=double(s->ring.starved.load()); stats[3]=s->error.load();
    stats[4]=s->latency.load(); stats[5]=s->peak.load();
    stats[6]=double(s->discontinuities.load());
}
