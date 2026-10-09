"""Execute Cemu's actual presentation methods with recording Vulkan boundaries.

This checks dynamic-state ownership, not GPU rendering or device image quality.
The guest's unchanged cached viewport/scissor must survive TV, pad, and ImGui.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = Path(json.loads((ROOT / "engines/cemu-source-lock.json").read_text())["core"]["stagedTree"])
SOURCE = (TREE / "src/Cafe/HW/Latte/Renderer/Vulkan/VulkanRenderer.cpp").read_text()


def function(name):
    start = SOURCE.index("void VulkanRenderer::" + name + "(")
    brace = SOURCE.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[start:end]


HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <utility>
#include <vector>
using sint32 = int;
using uint8 = unsigned char;
using VkPipelineStageFlags = int;
enum { VK_STRUCTURE_TYPE_MEMORY_BARRIER, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT=1,
 VK_PIPELINE_STAGE_TRANSFER_BIT=2, VK_PIPELINE_STAGE_VERTEX_SHADER_BIT=4,
 VK_PIPELINE_STAGE_GEOMETRY_SHADER_BIT=8, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT=16,
 VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT=1, VK_ACCESS_TRANSFER_WRITE_BIT=2,
 VK_ACCESS_COLOR_ATTACHMENT_READ_BIT=4, VK_ACCESS_SHADER_READ_BIT=8,
 VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO=9, VK_SUBPASS_CONTENTS_INLINE=10,
 VK_IMAGE_ASPECT_COLOR_BIT=1, VK_PIPELINE_BIND_POINT_GRAPHICS=11 };
struct Extent { unsigned width, height; bool operator==(const Extent&) const = default; };
struct Offset { int x, y; bool operator==(const Offset&) const = default; };
struct VkRect2D { Offset offset; Extent extent; bool operator==(const VkRect2D&) const = default; };
struct VkViewport { float x,y,width,height,minDepth,maxDepth; bool operator==(const VkViewport&) const = default; };
struct VkMemoryBarrier { int sType,srcAccessMask,dstAccessMask; };
struct VkRenderPassBeginInfo { int sType,renderPass,framebuffer; VkRect2D renderArea; int clearValueCount; };
struct Color { float r,g,b,a; };
struct VkClearAttachment { Color clearValue; int colorAttachment,aspectMask; };
struct VkClearRect { VkRect2D rect; int baseArrayLayer,layerCount; };
struct LatteTextureView {};
struct LatteTextureViewVk : LatteTextureView {};
struct RendererOutputShader { int FillUniformBlockBuffer(LatteTextureView&,std::pair<int,int>,bool) { return 1; } };
VkViewport activeViewport;
VkRect2D activeScissor;
bool inPass = false, overlayHasDraws = true;
void vkCmdSetViewport(int,int,int,const VkViewport* p) { activeViewport=*p; }
void vkCmdSetScissor(int,int,int,const VkRect2D* p) { activeScissor=*p; }
void vkCmdBeginRenderPass(int,const VkRenderPassBeginInfo*,int) { assert(!inPass); inPass=true; }
void vkCmdEndRenderPass(int) { assert(inPass); inPass=false; }
template<class... T> void vkCmdPipelineBarrier(T...) {}
template<class... T> void vkCmdClearAttachments(T...) {}
template<class... T> void vkCmdBindPipeline(T...) {}
template<class... T> void vkCmdBindDescriptorSets(T...) {}
template<class... T> void vkCmdDraw(T...) { assert(inPass); }
namespace ImGui { void Render() {} void* GetDrawData() { return nullptr; } }
void ImGui_ImplVulkan_RenderDrawData(void*,int) {
 if (overlayHasDraws) {
  activeViewport={0,0,1920,1080,0,1};
  activeScissor={{1200,50},{640,80}};
 }
}
struct Chain {
 Extent m_actualExtent;
 int m_swapchainRenderPass=1, m_swapchainFramebuffers[1]={2}, swapchainImageIndex=0;
 bool hasDefinedSwapchainImage=false;
 Extent getExtent() { return m_actualExtent; }
};
struct VulkanRenderer {
 struct State { int currentCommandBuffer=1,currentPipeline=0;
  VkViewport currentViewport{5,7,854,480,0,1};
  VkRect2D currentScissorRect{{17,29},{320,240}};
 } m_state;
 Chain tv{{1920,1080}},pad{{1240,1080}};
 bool acquire=true;
 int m_swapchainDescriptorSetLayout=0,m_pipelineLayout=0;
 bool AcquireNextSwapchainImage(bool) { return acquire; }
 Chain& GetChainInfo(bool main) { return main ? tv : pad; }
 void draw_endRenderPass() { if (inPass) vkCmdEndRenderPass(1); }
 template<class... T> int backbufferBlit_createGraphicsPipeline(T...) { return 2; }
 template<class... T> int backbufferBlit_createDescriptorSet(T...) { return 3; }
 unsigned uniformData_uploadUniformDataBufferGetOffset(std::pair<uint8*,size_t>) { return 0; }
 void ImguiEnd();
 void DrawBackbufferQuad(LatteTextureView*,RendererOutputShader*,bool,sint32,sint32,sint32,sint32,bool,bool);
 void beginGuest() { activeViewport=m_state.currentViewport; activeScissor=m_state.currentScissorRect; }
 bool guestStateIntact() const {
  // The guest cache sees unchanged GX2 state and emits no new commands here.
  return activeViewport==m_state.currentViewport && activeScissor==m_state.currentScissorRect && !inPass;
 }
};
'''


class CemuRenderStateRestoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang++")
        if not compiler:
            raise RuntimeError("clang++ required for actual-method regression")
        cls.temp = tempfile.TemporaryDirectory(prefix="cemu-render-state-")
        cls.addClassCleanup(cls.temp.cleanup)
        source = Path(cls.temp.name) / "test.cpp"
        cls.binary = Path(cls.temp.name) / "test"
        source.write_text(HARNESS + function("ImguiEnd") + function("DrawBackbufferQuad") + r'''
int main(int argc,char** argv) {
 assert(argc==2);
 VulkanRenderer r;
 LatteTextureViewVk texture;
 RendererOutputShader shader;
 r.beginGuest();
 if (argv[1][0]=='o') {
  overlayHasDraws=argv[1][1]=='1';
  inPass=true;
  r.ImguiEnd();
 } else {
  bool pad=argv[1][0]=='p';
  r.acquire=argv[1][0]!='f';
  r.DrawBackbufferQuad(&texture,&shader,true,100,180,960,720,pad,true);
  assert(r.GetChainInfo(!pad).hasDefinedSwapchainImage==r.acquire);
 }
 if (!r.guestStateIntact()) {
  std::fprintf(stderr,"presentation leaked dynamic viewport/scissor into unchanged guest state\n");
  return 1;
 }
}
''')
        subprocess.run([compiler, "-std=c++20", str(source), "-o", str(cls.binary)], check=True)

    def check(self, mode):
        result = subprocess.run([str(self.binary), mode], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overlay_draw_restores_guest_state(self):
        self.check("o1")

    def test_empty_overlay_preserves_guest_state(self):
        self.check("o0")

    def test_tv_presentation_restores_guest_state(self):
        self.check("tv")

    def test_pad_presentation_restores_guest_state(self):
        self.check("pad")

    def test_failed_acquire_preserves_guest_state(self):
        self.check("failed")


if __name__ == "__main__":
    unittest.main()
