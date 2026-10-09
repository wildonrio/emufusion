"""Execute the actual candidate Present method with a deterministic scheduler.

Proves publication and command ordering, not GPU or device timing behavior.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('source',type=Path)
args=p.parse_args()
source=args.source.read_text()
start=source.index('void PresentManager::Present(Frame* frame) {')
end=source.index('\nvoid PresentManager::RecreateFrame',start)
method=source[start:end]
harness=r'''
#include <cassert>
#include <deque>
#include <functional>
#include <mutex>
#include <vector>
namespace vk {struct CommandBuffer{};}
struct Frame {};
struct CV {int notifications{}; void notify_one(){++notifications;}};
struct Scheduler {
    std::vector<std::function<void(vk::CommandBuffer)>> pending;
    std::deque<std::function<void(vk::CommandBuffer)>> worker;
    int dispatches{},waits{},flushes{};
    template<class F> void Record(F f){pending.emplace_back(f);}
    void DispatchWork(){++dispatches; for(auto& f:pending)worker.push_back(f);pending.clear();}
    void Drain(){while(!worker.empty()){auto f=worker.front();worker.pop_front();f({});}}
    void WaitWorker(){++waits;DispatchWork();Drain();}
};
struct PresentManager {
    bool use_present_thread=true;
    Scheduler scheduler;
    std::mutex queue_mutex;
    std::deque<Frame*> present_queue,free_queue;
    CV frame_cv;
    bool render_submitted=false;
    int copies{};
    void CopyToSwapchain(Frame*){assert(render_submitted);++copies;}
    void Present(Frame*);
};
'''+method+r'''
int main(){
    PresentManager manager;
    Frame frame;
    manager.scheduler.Record([&](vk::CommandBuffer){manager.render_submitted=true;});
    manager.scheduler.DispatchWork(); // Renderer Flush's already dispatched submission.
    manager.Present(&frame);
    assert(manager.scheduler.pending.empty()); // No dependence on the NEXT guest frame.
    assert(!manager.render_submitted && manager.present_queue.empty()); // Still asynchronous.
    assert(manager.scheduler.waits==0);
    manager.scheduler.Drain();
    assert(manager.render_submitted);
    assert(manager.present_queue.size()==1 && manager.present_queue.front()==&frame);
    assert(manager.frame_cv.notifications==1);
    assert(manager.copies==0); // Dedicated presenter retains ownership of copy.
    PresentManager direct;
    direct.use_present_thread=false;
    direct.scheduler.Record([&](vk::CommandBuffer){direct.render_submitted=true;});
    direct.Present(&frame);
    assert(direct.scheduler.waits==1 && direct.copies==1 && direct.free_queue.front()==&frame);
}
'''
with tempfile.TemporaryDirectory(prefix='eden-present-dispatch-') as temp:
    cpp=Path(temp)/'test.cpp';binary=Path(temp)/'test'
    cpp.write_text(harness)
    subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('Actual Present method: immediate FIFO publication and unchanged synchronous path pass')
