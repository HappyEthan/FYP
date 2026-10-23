#include <iostream>
#include "/home/ethan/FYP/firmware/mlx_s3_monitor_fixed90/frame_guard.h"
int main(){FrameGuard g(1000,250,5);g.commit({2132.4f,2979.15f,-7084.55f});MagFrame bad{2119.2f,2995.05f,-0.242f},out{};bool retry=g.requiresRetry(bad);bool accepted=g.resolveRetry(bad,bad,out);std::cout<<"requires_retry="<<retry<<" repeated_identical_jump_accepted="<<accepted<<" accepted_z="<<out.z<<"\n";return !(retry&&accepted);}
