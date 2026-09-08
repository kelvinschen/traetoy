#import <Foundation/Foundation.h>
#import <CoreBluetooth/CoreBluetooth.h>
#include <stdint.h>
#include <string.h>

static NSString * const SERVICE=@"A32D1000-3B47-4A84-9E3F-217158CD0001";
static NSString * const INFO=@"A32D1001-3B47-4A84-9E3F-217158CD0001";
static NSString * const RX=@"A32D1002-3B47-4A84-9E3F-217158CD0001";
static NSString * const TX=@"A32D1003-3B47-4A84-9E3F-217158CD0001";
@interface PassportBLE : NSObject<CBCentralManagerDelegate,CBPeripheralDelegate>
@property CBCentralManager *central;
@property CBPeripheral *peripheral;
@property CBCharacteristic *infoChar,*rx,*tx;
@property dispatch_queue_t queue;
@property dispatch_semaphore_t waiter;
@property NSString *target,*failure;
@property NSData *result,*identity;
@property NSInteger operation;
@property BOOL requested;
- (void)finish:(NSString *)failure value:(NSData *)value;
- (void)scan;
- (void)disconnect;
@end
@implementation PassportBLE
- (instancetype)init {
    if((self=[super init])){
        _queue=dispatch_queue_create("cn.traetoy.passport.ble",DISPATCH_QUEUE_SERIAL);
        _central=[[CBCentralManager alloc]initWithDelegate:self queue:_queue options:@{CBCentralManagerOptionShowPowerAlertKey:@NO}];
    }return self;
}
- (void)finish:(NSString *)failure value:(NSData *)value {
    if(!self.waiter)return;
    self.failure=failure;self.result=value;
    dispatch_semaphore_t sem=self.waiter;self.waiter=nil;dispatch_semaphore_signal(sem);
}
- (void)disconnect {
    [self.central stopScan];
    self.peripheral.delegate=nil;
    if(self.peripheral)[self.central cancelPeripheralConnection:self.peripheral];
    self.peripheral=nil;self.rx=nil;self.tx=nil;self.infoChar=nil;self.identity=nil;
}
- (void)scan {
    if(!self.waiter||self.operation!=0)return;
    switch(self.central.state){
        case CBManagerStatePoweredOn:
            [self.central scanForPeripheralsWithServices:@[[CBUUID UUIDWithString:SERVICE]] options:@{CBCentralManagerScanOptionAllowDuplicatesKey:@YES}];break;
        case CBManagerStateUnauthorized:[self finish:@"Bluetooth permission denied; allow Bluetooth access in Privacy & Security > Bluetooth" value:nil];break;
        case CBManagerStatePoweredOff:[self finish:@"Bluetooth is turned off" value:nil];break;
        case CBManagerStateUnsupported:[self finish:@"Bluetooth LE is unsupported" value:nil];break;
        default:break;
    }
}
- (void)centralManagerDidUpdateState:(CBCentralManager *)central {
    if(central.state==CBManagerStatePoweredOn)[self scan];
    else if(self.waiter)[self scan];
}
- (void)centralManager:(CBCentralManager *)central didDiscoverPeripheral:(CBPeripheral *)peripheral advertisementData:(NSDictionary *)advertisementData RSSI:(NSNumber *)RSSI {
    (void)RSSI;
    if(!self.waiter||self.operation!=0||self.peripheral)return;
    NSString *name=advertisementData[CBAdvertisementDataLocalNameKey]?:peripheral.name;
    if(![name isEqualToString:self.target])return;
    [central stopScan];self.peripheral=peripheral;peripheral.delegate=self;
    [central connectPeripheral:peripheral options:nil];
}
- (void)centralManager:(CBCentralManager *)central didConnectPeripheral:(CBPeripheral *)peripheral {
    (void)central;if(peripheral!=self.peripheral)return;
    [peripheral discoverServices:@[[CBUUID UUIDWithString:SERVICE]]];
}
- (void)centralManager:(CBCentralManager *)central didFailToConnectPeripheral:(CBPeripheral *)peripheral error:(NSError *)error {
    (void)central;if(peripheral!=self.peripheral)return;
    [self finish:error.localizedDescription?:@"BLE connection failed" value:nil];[self disconnect];
}
- (void)centralManager:(CBCentralManager *)central didDisconnectPeripheral:(CBPeripheral *)peripheral error:(NSError *)error {
    (void)central;if(peripheral!=self.peripheral)return;
    [self finish:error.localizedDescription?:@"BLE disconnected" value:nil];[self disconnect];
}
- (void)peripheral:(CBPeripheral *)peripheral didDiscoverServices:(NSError *)error {
    if(peripheral!=self.peripheral)return;
    if(error){[self finish:error.localizedDescription value:nil];return;}
    for(CBService *service in peripheral.services){if([service.UUID isEqual:[CBUUID UUIDWithString:SERVICE]]){
        [peripheral discoverCharacteristics:@[[CBUUID UUIDWithString:INFO],[CBUUID UUIDWithString:RX],[CBUUID UUIDWithString:TX]] forService:service];return;
    }}[self finish:@"Companion service missing" value:nil];
}
- (void)peripheral:(CBPeripheral *)peripheral didDiscoverCharacteristicsForService:(CBService *)service error:(NSError *)error {
    if(peripheral!=self.peripheral)return;
    if(error){[self finish:error.localizedDescription value:nil];return;}
    for(CBCharacteristic *c in service.characteristics){
        if([c.UUID isEqual:[CBUUID UUIDWithString:INFO]])self.infoChar=c;
        if([c.UUID isEqual:[CBUUID UUIDWithString:RX]])self.rx=c;
        if([c.UUID isEqual:[CBUUID UUIDWithString:TX]])self.tx=c;
    }
    if(!self.infoChar||!self.rx||!self.tx){[self finish:@"Companion characteristics missing" value:nil];return;}
    [peripheral readValueForCharacteristic:self.infoChar];
}
- (void)peripheral:(CBPeripheral *)peripheral didUpdateValueForCharacteristic:(CBCharacteristic *)c error:(NSError *)error {
    if(peripheral!=self.peripheral)return;
    if((self.operation==0&&c!=self.infoChar)||(self.operation==2&&c!=self.tx)||self.operation==1)return;
    if(error){[self finish:error.localizedDescription value:nil];return;}
    if(self.operation==0)self.identity=c.value;
    [self finish:nil value:c.value];
}
- (void)peripheral:(CBPeripheral *)peripheral didWriteValueForCharacteristic:(CBCharacteristic *)c error:(NSError *)error {
    if(peripheral!=self.peripheral||c!=self.rx||self.operation!=1)return;
    [self finish:error.localizedDescription value:[NSData data]];
}
@end

static PassportBLE *client;
static void initialize_client(void){static dispatch_once_t once;dispatch_once(&once,^{client=[PassportBLE new];});}
/* Single calling thread. Callbacks own the queue; no CoreBluetooth operations block it. */
int passport_ble_call(int op,const char *name,const uint8_t *data,size_t length,uint8_t *out,size_t capacity,char *error,size_t error_size,unsigned timeout_ms) {
    @autoreleasepool {
        initialize_client();dispatch_semaphore_t sem=dispatch_semaphore_create(0);
        NSData *payload=length?[NSData dataWithBytes:data length:length]:nil;
        NSString *target=name?[NSString stringWithUTF8String:name]:nil;
        dispatch_sync(client.queue,^{
            client.operation=op;client.waiter=sem;client.failure=nil;client.result=nil;
            if(op==0){
                if(client.requested && [CBManager authorization]==CBManagerAuthorizationNotDetermined){[client finish:@"Bluetooth permission is awaiting macOS approval; unlock the Mac and allow Bluetooth access" value:nil];return;}
                client.requested=YES;
                if(client.peripheral.state==CBPeripheralStateConnected&&client.identity){[client finish:nil value:client.identity];return;}
                [client disconnect];client.target=target;[client scan];
            }else if(!client.peripheral||client.peripheral.state!=CBPeripheralStateConnected){[client finish:@"BLE is not connected" value:nil];}
            else if(op==1){[client.peripheral writeValue:payload forCharacteristic:client.rx type:CBCharacteristicWriteWithResponse];}
            else if(op==2){[client.peripheral readValueForCharacteristic:client.tx];}
            else [client finish:@"Invalid BLE operation" value:nil];
        });
        uint64_t deadline=dispatch_time(DISPATCH_TIME_NOW,(int64_t)timeout_ms*NSEC_PER_MSEC);
        long waiting;
        do {
            if([NSThread isMainThread])[[NSRunLoop currentRunLoop]runMode:NSDefaultRunLoopMode beforeDate:[NSDate date]];
            waiting=dispatch_semaphore_wait(sem,dispatch_time(DISPATCH_TIME_NOW,50*NSEC_PER_MSEC));
        }while(waiting && dispatch_time(DISPATCH_TIME_NOW,0)<deadline);
        if(waiting){
            dispatch_sync(client.queue,^{
                NSString *reason=[NSString stringWithFormat:@"BLE operation timed out (adapter state=%ld, authorization=%ld)",(long)client.central.state,(long)[CBManager authorization]];
                if([CBManager authorization]==CBManagerAuthorizationNotDetermined)reason=@"Bluetooth permission is awaiting macOS approval; unlock the Mac and allow Bluetooth access";
                [client finish:reason value:nil];[client disconnect];
            });
        }
        __block int result=0;
        dispatch_sync(client.queue,^{
            if(client.failure){if(error_size)snprintf(error,error_size,"%s",client.failure.UTF8String);result=-1;}
            else if(client.result.length>capacity){if(error_size)snprintf(error,error_size,"BLE response too large");result=-1;}
            else {result=(int)client.result.length;if(result)memcpy(out,client.result.bytes,result);}
            client.result=nil;client.failure=nil;
        });return result;
    }
}
void passport_ble_disconnect(void){if(client)dispatch_sync(client.queue,^{[client disconnect];});}
