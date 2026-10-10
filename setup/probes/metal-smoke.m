#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#include <dispatch/dispatch.h>

// Self-authored workload: verify GPU results rather than just device enumeration.
static void Check(BOOL condition, NSString *message) {
    if (!condition) @throw [NSException exceptionWithName:@"MetalSmoke" reason:message userInfo:nil];
}

static void Finish(id<MTLCommandBuffer> command) {
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    [command addCompletedHandler:^(id<MTLCommandBuffer> completed) {
        dispatch_semaphore_signal(done);
    }];
    [command commit];
    Check(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC)) == 0,
          @"GPU completion timed out");
    Check(command.status == MTLCommandBufferStatusCompleted,
          [NSString stringWithFormat:@"GPU command failed: %@", command.error]);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSMutableDictionary *result = [@{@"pass": @NO} mutableCopy];
        NSWindow *window = nil;
        @try {
            BOOL gui = argc == 2 && strcmp(argv[1], "--gui") == 0;
            result[@"windowServerAttached"] = @(gui);
            if (gui) {
                [NSApplication sharedApplication];
                window = [[NSWindow alloc] initWithContentRect:NSMakeRect(32,32,96,64)
                    styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
                window.title = @"Metal probe";
                [window orderFront:nil];
                [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            }
            NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
            NSMutableArray *names = [NSMutableArray array];
            for (id<MTLDevice> candidate in devices) [names addObject:candidate.name];
            result[@"enumeratedDevices"] = names;
            id<MTLDevice> device = MTLCreateSystemDefaultDevice();
            result[@"systemDefaultDeviceAvailable"] = @(device != nil);
            if (!device) device = devices.firstObject;
            Check(device != nil, @"No Metal device");
            result[@"device"] = device.name;
            result[@"registryID"] = @(device.registryID);
            result[@"unifiedMemory"] = @(device.hasUnifiedMemory);
            id<MTLCommandQueue> queue = [device newCommandQueue];
            Check(queue != nil, @"No command queue");
            NSString *source = @"#include <metal_stdlib>\n"
                "using namespace metal;\n"
                "kernel void values(device uint *out [[buffer(0)]], uint i [[thread_position_in_grid]]) { out[i] = i * 3 + 7; }\n"
                "vertex float4 triangle(uint i [[vertex_id]]) {\n"
                "const float2 p[3] = {float2(-1,-1), float2(1,-1), float2(0,1)}; return float4(p[i],0,1); }\n"
                "fragment float4 red() { return float4(1,0,0,1); }\n";
            NSError *error = nil;
            id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
            Check(library != nil, [NSString stringWithFormat:@"Shader compilation: %@", error]);
            id<MTLComputePipelineState> computePipeline = [device newComputePipelineStateWithFunction:
                [library newFunctionWithName:@"values"] error:&error];
            Check(computePipeline != nil, [NSString stringWithFormat:@"Compute pipeline: %@", error]);
            id<MTLBuffer> output = [device newBufferWithLength:64 * sizeof(uint32_t) options:MTLResourceStorageModeShared];
            Check(output != nil, @"No compute output buffer");
            memset(output.contents, 0, output.length);
            id<MTLCommandBuffer> compute = [queue commandBuffer];
            id<MTLComputeCommandEncoder> encoder = [compute computeCommandEncoder];
            Check(encoder != nil, @"No compute encoder");
            [encoder setComputePipelineState:computePipeline];
            [encoder setBuffer:output offset:0 atIndex:0];
            [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];
            [encoder endEncoding];
            Finish(compute);
            uint32_t *values = output.contents;
            for (uint32_t i = 0; i < 64; ++i)
                Check(values[i] == i * 3 + 7, [NSString stringWithFormat:@"Compute mismatch at %u: %u", i, values[i]]);
            result[@"compute"] = @"64 exact integer results passed";

            MTLTextureDescriptor *descriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
                MTLPixelFormatRGBA8Unorm width:32 height:32 mipmapped:NO];
            descriptor.storageMode = MTLStorageModePrivate;
            descriptor.usage = MTLTextureUsageRenderTarget;
            id<MTLTexture> texture = [device newTextureWithDescriptor:descriptor];
            id<MTLBuffer> pixels = [device newBufferWithLength:256 * 32 options:MTLResourceStorageModeShared];
            Check(texture != nil && pixels != nil, @"Render resources unavailable");
            MTLRenderPipelineDescriptor *pipeline = [MTLRenderPipelineDescriptor new];
            pipeline.vertexFunction = [library newFunctionWithName:@"triangle"];
            pipeline.fragmentFunction = [library newFunctionWithName:@"red"];
            pipeline.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
            id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:pipeline error:&error];
            Check(state != nil, [NSString stringWithFormat:@"Render pipeline: %@", error]);
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = texture;
            pass.colorAttachments[0].loadAction = MTLLoadActionClear;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            pass.colorAttachments[0].clearColor = MTLClearColorMake(0,0,0,1);
            id<MTLCommandBuffer> draw = [queue commandBuffer];
            id<MTLRenderCommandEncoder> render = [draw renderCommandEncoderWithDescriptor:pass];
            Check(render != nil, @"No render encoder");
            [render setRenderPipelineState:state];
            [render drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [render endEncoding];
            id<MTLBlitCommandEncoder> blit = [draw blitCommandEncoder];
            Check(blit != nil, @"No blit encoder");
            [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(32,32,1) toBuffer:pixels destinationOffset:0
                destinationBytesPerRow:256 destinationBytesPerImage:256 * 32];
            [blit endEncoding];
            Finish(draw);
            uint8_t *bytes = pixels.contents;
            size_t center = 16 * 256 + 16 * 4, outside = 16 * 256;
            Check(bytes[center] == 255 && bytes[center+1] == 0 && bytes[center+2] == 0 && bytes[center+3] == 255,
                  @"Triangle center is not opaque red");
            Check(bytes[outside] == 0 && bytes[outside+1] == 0 && bytes[outside+2] == 0 && bytes[outside+3] == 255,
                  @"Outside triangle is not opaque black");
            result[@"render"] = @"Triangle and background exact readback passed";
            result[@"pass"] = @YES;
        } @catch (NSException *exception) {
            result[@"error"] = exception.reason ?: exception.name;
        }
        [window orderOut:nil];
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:nil];
        puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
        return [result[@"pass"] boolValue] ? 0 : 1;
    }
}
