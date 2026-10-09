// Isolated host equivalence probe. Never linked into the Android application.
#include <net.h>
#include <layer.h>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <chrono>
#ifdef EMUFUSION_VULKAN_PROBE
#include <gpu.h>
#include <command.h>
#include "rife_ops.h"
DEFINE_LAYER_CREATOR(Warp)
alignas(64) thread_local volatile int android_tls_alignment_anchor=0;
#endif

// CPU reference for the existing RIFE pixel-displacement/border/bilinear warp.
// This does not claim the Vulkan implementation has been exercised.
class ReferenceWarp:public ncnn::Layer {
public:
    int forward(const std::vector<ncnn::Mat>& in,std::vector<ncnn::Mat>& out,
                const ncnn::Option& opt) const override {
        const auto& im=in[0];const auto& flow=in[1];
        if(flow.c!=2||flow.w!=im.w||flow.h!=im.h) return -1;
        out[0].create(im.w,im.h,im.c,4u,1,opt.blob_allocator);
        if(out[0].empty()) return -100;
        for(int c=0;c<im.c;c++) for(int y=0;y<im.h;y++) for(int x=0;x<im.w;x++) {
            float sx=x+flow.channel(0).row(y)[x],sy=y+flow.channel(1).row(y)[x];
            int x0=(int)std::floor(sx),y0=(int)std::floor(sy),x1=x0+1,y1=y0+1;
            x0=std::clamp(x0,0,im.w-1);x1=std::clamp(x1,0,im.w-1);
            y0=std::clamp(y0,0,im.h-1);y1=std::clamp(y1,0,im.h-1);
            float ax=sx-x0,ay=sy-y0;
            float a=im.channel(c).row(y0)[x0]*(1-ax)+im.channel(c).row(y0)[x1]*ax;
            float b=im.channel(c).row(y1)[x0]*(1-ax)+im.channel(c).row(y1)[x1]*ax;
            out[0].channel(c).row(y)[x]=a*(1-ay)+b*ay;
        }
        return 0;
    }
};
DEFINE_LAYER_CREATOR(ReferenceWarp)

static std::vector<unsigned char> read(const char* path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open input");
    std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
    if (data.size()!=256*192*4) throw std::runtime_error("unexpected geometry");
    return data;
}
static ncnn::Mat input(const std::vector<unsigned char>& rgba) {
    ncnn::Mat image(256,192,3);
    for(int c=0;c<3;c++) for(int y=0;y<192;y++) for(int x=0;x<256;x++)
        image.channel(c).row(y)[x]=rgba[((191-y)*256+x)*4+c]/255.f;
    return image;
}
int main(int argc,char** argv) try {
    if(argc<6||argc>9) throw std::runtime_error("usage: probe param bin left.rgba right.rgba expected.rgba [iterations] [fp16-storage:0|1] [resident]");
    int iterations=argc>=7?std::stoi(argv[6]):1;
    const bool fp16=argc>=8&&std::string(argv[7])=="1";
    if(argc>=8&&std::string(argv[7])!="0"&&std::string(argv[7])!="1")throw std::runtime_error("invalid precision");
    const bool resident=argc==9;
    if(resident&&std::string(argv[8])!="resident")throw std::runtime_error("invalid mode");
#ifndef EMUFUSION_VULKAN_PROBE
    if(resident)throw std::runtime_error("resident mode requires Vulkan build");
#endif
    if(iterations<1||iterations>100)throw std::runtime_error("iterations must be 1..100");
    ncnn::Net net;
#ifdef EMUFUSION_VULKAN_PROBE
    android_tls_alignment_anchor=1;
    ncnn::create_gpu_instance();
    if(ncnn::get_gpu_count()<1) throw std::runtime_error("no Vulkan device");
    net.set_vulkan_device(0);
    net.opt.use_vulkan_compute=true;
#else
    net.opt.use_vulkan_compute=false;
#endif
    net.opt.use_fp16_packed=fp16;net.opt.use_fp16_storage=fp16;net.opt.use_fp16_arithmetic=false;
    net.opt.num_threads=4;
#ifdef EMUFUSION_VULKAN_PROBE
    net.register_custom_layer("rife.Warp",Warp_layer_creator);
#else
    net.register_custom_layer("rife.Warp",ReferenceWarp_layer_creator);
#endif
    if(net.load_param(argv[1]) || net.load_model(argv[2])) throw std::runtime_error("graph load failed");
#ifdef EMUFUSION_VULKAN_PROBE
    for(const auto* layer:net.layers()) {
        if(layer->type!="Input"&&!layer->support_vulkan)
            throw std::runtime_error("CPU-only layer rejected: "+layer->type+" "+layer->name);
    }
#endif
    auto left=input(read(argv[3]));auto right=input(read(argv[4]));auto expected=read(argv[5]);
    ncnn::Mat out;
#ifdef EMUFUSION_VULKAN_PROBE
    auto* vkdev=ncnn::get_gpu_device(0);
    ncnn::Option gpuopt=net.opt;
    auto* blob=vkdev->acquire_blob_allocator();auto* staging=vkdev->acquire_staging_allocator();
    gpuopt.blob_vkallocator=blob;gpuopt.workspace_vkallocator=blob;gpuopt.staging_vkallocator=staging;
    ncnn::VkMat gpu_left,gpu_right,gpu_out;
    if(resident) {
        ncnn::VkCompute upload(vkdev);
        upload.record_upload(left,gpu_left,gpuopt);upload.record_upload(right,gpu_right,gpuopt);
        if(upload.submit_and_wait())throw std::runtime_error("upload failed");
    }
#endif
    std::vector<double> times;
    const int warmup=iterations>1?3:0;
    for(int i=-warmup;i<iterations;i++) {
        auto start=std::chrono::steady_clock::now();
        auto ex=net.create_extractor();
#ifdef EMUFUSION_VULKAN_PROBE
        if(resident) {
            ex.set_blob_vkallocator(blob);ex.set_workspace_vkallocator(blob);ex.set_staging_vkallocator(staging);
            ncnn::VkCompute command(vkdev);gpu_out.release();
            if(ex.input("in0",gpu_left)||ex.input("in1",gpu_right)||ex.extract("out2",gpu_out,command))
                throw std::runtime_error("resident extraction failed");
            if(command.submit_and_wait())throw std::runtime_error("compute failed");
        } else
#endif
        {
            if(ex.input("in0",left)||ex.input("in1",right)) throw std::runtime_error("input failed");
            out.release();
            if(ex.extract("out2",out))throw std::runtime_error("extraction failed");
        }
        double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        if(i>=0)times.push_back(ms);
    }
#ifdef EMUFUSION_VULKAN_PROBE
    if(resident) {
        ncnn::VkCompute download(vkdev);download.record_download(gpu_out,out,gpuopt);
        if(download.submit_and_wait())throw std::runtime_error("download failed");
    }
#endif
    if(out.w!=256||out.h!=192||out.c!=3||out.elempack!=1||out.elemsize!=4u)
        throw std::runtime_error("invalid output");
    double total=0;int maximum=0,over2=0;
    for(int c=0;c<3;c++) for(int y=0;y<192;y++) for(int x=0;x<256;x++) {
        float value=out.channel(c).row(y)[x];
        if(!std::isfinite(value)) throw std::runtime_error("nonfinite output");
        int actual=std::clamp((int)std::nearbyint(value*255.f),0,255);
        int error=std::abs(actual-(int)expected[((191-y)*256+x)*4+c]);
        total+=error;maximum=std::max(maximum,error);over2+=error>2;
    }
    std::cout<<"{\"max_byte_error\":"<<maximum<<",\"mean_byte_error\":"<<total/(256*192*3)
             <<",\"components_over2\":"<<over2<<",\"android_qualified\":false,\"fp16_storage\":"<<(fp16?"true":"false")<<",\"warmup\":"<<warmup
             <<",\"gpu_resident\":"<<(resident?"true":"false")<<",\"inference_ms\":[";
    for(size_t i=0;i<times.size();i++)std::cout<<(i?",":"")<<times[i];
    std::cout<<"]}\n";
#ifdef EMUFUSION_VULKAN_PROBE
    gpu_out.release();gpu_left.release();gpu_right.release();net.clear();
    vkdev->reclaim_blob_allocator(blob);vkdev->reclaim_staging_allocator(staging);
#endif
    return maximum<=2?0:2;
} catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}
